"""Explicit, operator-bound native GUI control; never discover or launch a GUI.

Native replies are retained under ``response``; the transport envelope is not an
engine-command abstraction. See docs/control.md for the security boundary.
"""
from __future__ import annotations

import errno
import ipaddress
import select
import math
import os
from pathlib import Path
import queue
import socket
import stat
import subprocess
import threading
import time

from .config import native_platform, require_app
from .rpc import RpcError, Session, canonical, strict_json
from .processes import OwnedPopen, CURRENT_EXECUTION, current_execution

MAX_RESPONSE = 64 * 1024 * 1024
MAX_REQUEST = 96 * 1024 * 1024
MAX_SECRET_FILE = 64 * 1024


class ControlError(ValueError):
    """Sanitized control failure; never includes native input or secret material."""


class ControlExecutionError(ControlError, RpcError):
    """Keep direct-call compatibility and API cancellation/deadline codes."""
    def __init__(self, code, message):
        RpcError.__init__(self, code, message)


def profiles():
    return strict_json(Path(__file__).with_name('control_profiles.json').read_text(encoding='utf-8'))


def _remaining(deadline):
    try:
        shared = current_execution().remaining()
    except RpcError as exc:
        reason = 'cancelled' if exc.error.get('code') == -32800 else 'timeout'
        raise ControlExecutionError(exc.error['code'], f'Control {reason}; outcome unknown; no retry performed') from None
    remaining = min(shared, deadline - time.monotonic())
    if remaining <= 0:
        raise ControlExecutionError(-32012, 'Control timeout; outcome unknown; no retry performed')
    return remaining


def _endpoint(value):
    if not isinstance(value, dict) or set(value) != {'host', 'port'}:
        raise ControlError('Operator endpoint must contain exactly host and port')
    host, port = value['host'], value['port']
    if not isinstance(host, str):
        raise ControlError('Control endpoint requires a literal loopback IP')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        raise ControlError('Control endpoint requires a literal loopback IP; no DNS or URLs') from None
    if not address.is_loopback or '%' in host:
        raise ControlError('Only loopback control endpoints are permitted')
    if type(port) is not int or not 1 <= port <= 65535:
        raise ControlError('Invalid operator control port')
    return str(address), port


def _private_file(value):
    """Read a bounded regular file without following a swapped final symlink."""
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ControlError('An absolute operator-owned credential file is required')
    path = Path(value)
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or path.is_symlink():
            raise ControlError('Credential file must be a private regular file, not a symlink')
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(path, flags)
        with os.fdopen(fd, 'rb') as stream:
            opened = os.fstat(stream.fileno())
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise ControlError('Credential file changed while opening')
            if os.name != 'nt' and (opened.st_uid != os.getuid() or opened.st_mode & 0o077):
                raise ControlError('Credential file requires current-user ownership and mode 0600')
            data = stream.read(MAX_SECRET_FILE + 1)
        if len(data) > MAX_SECRET_FILE:
            raise ControlError('Credential file exceeds size limit')
        return data.decode('utf-8').strip()
    except (OSError, UnicodeError):
        raise ControlError('Could not securely read operator credential file') from None


def _secret(value):
    if not isinstance(value, str) or not value or len(value) > MAX_SECRET_FILE or any(c.isspace() for c in value):
        raise ControlError('Invalid control credential')
    return value


def _contains_secret(value, secret):
    """Inspect JSON strings before serialization, including encoded text blocks."""
    if not secret:
        return False
    pending = [value]
    seen = set()
    escaped = canonical(secret)[1:-1]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)
        elif isinstance(item, str):
            if secret in item or escaped in item:
                return True
            if item in seen:
                continue
            seen.add(item)
            try:
                decoded = strict_json(item)
            except (ValueError, TypeError, RecursionError):
                continue
            pending.append(decoded)
    return False


def _no_secret(value, secret):
    # Refuse rather than silently changing a native payload.
    if _contains_secret(value, secret):
        raise ControlError('Native response withheld because it contains control credentials')
    return value


def _parse(data):
    try:
        return strict_json(data.decode('utf-8'))
    except (ValueError, UnicodeError, RecursionError):
        raise ControlError('Invalid native control JSON response; outcome unknown') from None


def _socket_ready(sock, deadline, writing=False):
    # Poll readiness on the SAME connection; never retry a native request.
    while True:
        wait = min(0.05, _remaining(deadline))
        readable, writable, errors = select.select([] if writing else [sock], [sock] if writing else [], [sock], wait)
        _remaining(deadline)
        if errors:
            raise OSError('Control socket failed')
        if readable or writable:
            return


def _frame(sock, message, deadline, secret):
    data = (canonical(message) + '\n').encode('utf-8')
    if len(data) > MAX_REQUEST:
        raise ControlError('Control request exceeds size limit')
    pending = memoryview(data)
    while pending:
        _socket_ready(sock, deadline, writing=True)
        _remaining(deadline)  # Last fence before effectful dispatch/continuation.
        try:
            sent = sock.send(pending)
        except BlockingIOError:
            continue
        if not sent:
            raise OSError('Control connection closed during send')
        pending = pending[sent:]
    data = bytearray()
    while True:
        _socket_ready(sock, deadline)
        try:
            block = sock.recv(min(65536, MAX_RESPONSE + 1 - len(data)))
        except BlockingIOError:
            continue
        _remaining(deadline)
        if not block:
            raise ControlError('Control connection closed before full reply; outcome unknown')
        data.extend(block)
        if len(data) > MAX_RESPONSE:
            raise ControlError('Control response exceeds size limit; outcome unknown')
        if b'\n' in block:
            line, rest = data.split(b'\n', 1)
            if rest.strip():
                raise ControlError('Unexpected extra control response; outcome unknown')
            response = _no_secret(_parse(line), secret)
            if not isinstance(response, dict):
                raise ControlError('Control reply must be an object')
            if 'id' in response and (type(response['id']) is not int or response['id'] != message['id']):
                raise ControlError('Mismatched control response id; outcome unknown')
            if message.get('jsonrpc') == '2.0':
                valid = response.get('jsonrpc') == '2.0' and ('result' in response) != ('error' in response)
            else:
                valid = type(response.get('ok')) is bool
            if not valid or ('id' not in response and response.get('ok') is not False):
                raise ControlError('Invalid control response envelope; outcome unknown')
            return response


def _tcp(endpoint, method, params, auth, secret, deadline):
    host, port = endpoint
    family = socket.AF_INET6 if ':' in host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.setblocking(False)
            _remaining(deadline)
            status = sock.connect_ex((host, port))
            pending = {0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, 10035, 10036, 10037}
            if status not in pending:
                raise OSError('Control connection failed')
            _socket_ready(sock, deadline, writing=True)
            if sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR):
                raise OSError('Control connection failed')
            base = {'jsonrpc': '2.0'} if auth == 'pdf-token' else {}
            if auth in ('photo-token', 'pdf-token'):
                reply = _frame(sock, dict(base, id=1, method='auth', params={'token': secret}), deadline, secret)
                if (reply.get('ok') is not True if auth == 'photo-token' else 'error' in reply):
                    raise ControlError('Control authentication refused')
            request = dict(base, id=2, method=method, params=params)
            if auth == 'word-key':
                request['key'] = secret
            return _frame(sock, request, deadline, secret)
    except (OSError, TimeoutError):
        raise ControlError('Control transport failed or timed out; outcome unknown; no retry performed') from None


def _cli(command, deadline):
    """Bound stdout while running; discard stderr rather than expose credentials."""
    kwargs = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.PIPE, 'stderr': subprocess.DEVNULL, 'shell': False}
    if os.name == 'nt':
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    try:
        process = OwnedPopen(command, **kwargs)
    except OSError:
        raise ControlError('Native control CLI could not start') from None
    result = queue.Queue(maxsize=1)

    def read():
        try:
            result.put(process.stdout.read(MAX_RESPONSE + 1))
        except (OSError, ValueError):
            result.put(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        while True:
            try:
                data = result.get(timeout=min(0.05, _remaining(deadline)))
                break
            except queue.Empty:
                continue
        _remaining(deadline)
        if data is None or len(data) > MAX_RESPONSE:
            raise ControlError('Native control output missing or exceeds size limit; outcome unknown')
        while True:
            try:
                code = process.wait(timeout=min(0.05, _remaining(deadline)))
                break
            except subprocess.TimeoutExpired:
                continue
        _remaining(deadline)
        if code:
            raise ControlError('Native control CLI failed; stderr withheld; inspect app state')
        return _parse(data)
    finally:
        process.close_tree()
        if process.poll() is None:
            process.kill()  # Only our CLI, never a running GUI.
            process.wait()
        reader.join(timeout=2)
        process.stdout.close()


def call_control(store, arguments, timeout=60):
    """Bind direct callers to the same budget used by API-dispatched control."""
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ControlError('Control timeout must be a positive finite number')
    execution = current_execution(timeout)
    token = CURRENT_EXECUTION.set(execution)
    try:
        _remaining(execution.deadline)
        return _call_control(store, arguments, execution.deadline)
    finally:
        CURRENT_EXECUTION.reset(token)


def _call_control(store, arguments, deadline):
    """Run one exact vendor method. Caller routes foreign platforms beforehand.

    Only app/method/params/control_name/platform are accepted. Network addresses,
    credentials, executable argv and filesystem roots cannot come from a call.
    """
    if not isinstance(arguments, dict) or set(arguments) - {'app', 'method', 'params', 'control_name', 'platform'}:
        raise ControlError('Control accepts only app, method, params, control_name and platform')
    app = require_app(arguments.get('app'))
    platform = arguments.get('platform', 'local')
    if platform not in (None, 'local', native_platform()):
        raise ControlError('Route the whole control operation to the configured native host first; no local fallback')
    _remaining(deadline)
    method = arguments.get('method')
    if not isinstance(method, str) or not method or any(ord(c) < 32 for c in method) or method.startswith('-'):
        raise ControlError('A nonempty vendor method name is required (not CLI options)')
    if method == 'auth':
        raise ControlError('Authentication is owned by the control transport')
    params = arguments.get('params', {})
    try:
        encoded = canonical({'method': method, 'params': params}).encode('utf-8')
        pending = [params]
        while pending:
            item = pending.pop()
            if type(item) is dict:
                if any(type(key) is not str for key in item):
                    raise ValueError('JSON object keys must be strings')
                pending.extend(item.values())
            elif type(item) is list:
                pending.extend(item)
            elif item is not None and type(item) not in (str, int, float, bool):
                raise ValueError('Only JSON data types are accepted')
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ControlError('Control params must be finite JSON data') from None
    if len(encoded) > MAX_REQUEST:
        raise ControlError('Control request exceeds size limit')
    setting = store.config.get('apps', {}).get(app, {})
    control = setting.get('control') if isinstance(setting, dict) else None
    name = arguments.get('control_name')
    if name is not None:
        if not isinstance(name, str) or not name or not isinstance(control, dict):
            raise ControlError('Unknown operator control_name')
        named = control.get('named', {})
        if not isinstance(named, dict):
            raise ControlError('Invalid operator named control configuration')
        control = named.get(name)
    if not isinstance(control, dict) or not control:
        raise ControlError('No operator control configuration; nothing connected or launched')
    profile = profiles()[app]
    allowed = {'transport', 'named'}
    if profile['auth'] == 'pdf-token':
        allowed.add('control_file')
    else:
        allowed.add('endpoint')
        if profile['auth'] == 'photo-token':
            allowed.add('token_file')
        elif profile['auth'] == 'word-key':
            allowed.add('key_file')
    if set(control) - allowed:
        raise ControlError('Unsupported operator control fields; roots/argv cannot be overridden here')
    transport = control.get('transport', profile['transport'])
    if transport not in (profile['transport'], 'tcp-jsonl'):
        raise ControlError('Unsupported control transport for this source-audited app')
    _remaining(deadline)
    secret = None
    auth = profile['auth']
    if auth == 'pdf-token':
        try:
            info = strict_json(_private_file(control.get('control_file')))
        except ValueError:
            raise ControlError('Invalid private PDF control file') from None
        if not isinstance(info, dict):
            raise ControlError('Invalid private PDF control file')
        endpoint = _endpoint({'host': '127.0.0.1', 'port': info.get('port')})
        secret = _secret(info.get('token'))
    else:
        endpoint = _endpoint(control.get('endpoint'))
        if auth in ('photo-token', 'word-key'):
            secret = _secret(_private_file(control.get('token_file' if auth == 'photo-token' else 'key_file')))
    _remaining(deadline)
    if _contains_secret({'method': method, 'params': params}, secret):
        raise ControlError('Control params must not contain transport credentials')
    # Native PDF's CLI only represents ui.* with object key=value params. All
    # other raw data shapes use its source-verified JSON-RPC TCP protocol.
    if transport == 'pdf-cli' and (not method.startswith('ui.') or not isinstance(params, dict) or any(not isinstance(k, str) or '=' in k or k.startswith('-') for k in params)):
        transport = 'tcp-jsonl'
    try:
        if transport == 'tcp-jsonl':
            response = _tcp(endpoint, method, params, auth, secret, deadline)
            ok = response.get('ok') is True if auth != 'pdf-token' else 'error' not in response
        else:
            executable = store.executable(app)
            if executable is None:
                raise ControlError('Native control CLI is not installed; no automatic install or fallback')
            host, port = endpoint
            address = f'[{host}]:{port}' if ':' in host else f'{host}:{port}'
            if transport == 'photo-mcp':
                command = [str(executable), 'mcp', '--bridge', address, '--control-token-file', control['token_file']]
                with Session(app, command, _remaining(deadline)) as session:
                    session.timeout = _remaining(deadline)
                    response = session.rpc('tools/call', {'name': 'control_call', 'arguments': {'method': method, 'params': params}})
                ok = not response.get('isError', False)
            elif transport == 'app-cli':
                response = _cli([str(executable), 'app', '--port', address, '--method', method, canonical(params)], deadline)
                ok = True
            elif transport == 'pdf-cli':
                args = [str(executable), 'ui', '--control', control['control_file'], method]
                args += [k + '=' + canonical(v) for k, v in params.items()]
                response = _cli(args, deadline)
                ok = True
            else:
                raise ControlError('Unsupported source-audited control transport')
        response = _no_secret(response, secret)
        _remaining(deadline)
        return {'ok': ok, 'app': app, 'transport': transport, 'response': response}
    except RpcError:
        _remaining(deadline)
        raise ControlError('Native control bridge failed; details withheld; outcome unknown; no retry performed') from None
