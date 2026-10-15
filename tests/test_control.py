"""Synthetic protocol tests. No real app, GUI, installed CLI or live config used."""
import contextlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from art_cli import control


class FakeStore:
    def __init__(self, app='cadcraft', setting=None):
        self.config = {'apps': {app: {'control': setting}}} if setting else {}

    def executable(self, app):
        return Path('/synthetic') / (app + '-cli')


@contextlib.contextmanager
def server(handler):
    """An explicitly synthetic, ephemeral loopback peer, never a discovered port."""
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    listener.settimeout(3)
    errors = []

    def run():
        try:
            with listener.accept()[0] as conn:
                conn.settimeout(3)
                with conn.makefile('rb') as reader:
                    handler(conn, reader)
        except (OSError, TimeoutError):
            pass
        except Exception as exc:
            errors.append(exc)
        finally:
            listener.close()

    thread = threading.Thread(target=run)
    thread.start()
    try:
        yield {'host': '127.0.0.1', 'port': listener.getsockname()[1]}
    finally:
        thread.join(4)
        listener.close()
        if errors:
            raise errors[0]


def reply(conn, request, result=None, **extra):
    value = {'id': request['id'], 'ok': True, 'result': result}
    value.update(extra)
    conn.sendall((json.dumps(value) + '\n').encode())


class ControlTests(unittest.TestCase):
    def private(self, folder, name, value):
        path = Path(folder) / name
        path.write_text(value, encoding='utf-8')
        os.chmod(path, 0o600)
        return str(path)

    def test_all_thirteen_source_profiles(self):
        profiles = control.profiles()
        self.assertEqual(len(profiles), 13)
        for app, profile in profiles.items():
            self.assertFalse(profile['method_hints_are_allowlist'])
            self.assertEqual(len(profile['commit']), 40)
            self.assertRegex(profile['commit'], r'^[0-9a-f]{40}$')
            self.assertTrue(profile['source_url'].startswith('https://github.com/storytold/'+app+'/blob/'+profile['commit']+'/'))
            self.assertEqual(profile['screenshot_method'], 'ui.screenshot')

    def test_missing_config_never_connects_or_spawns(self):
        with patch.object(socket.socket, 'connect') as connect, patch.object(control.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(control.ControlError, 'No operator'):
                control.call_control(FakeStore(), {'app': 'cadcraft', 'method': 'ui.inspect'})
            connect.assert_not_called()
            spawn.assert_not_called()

    def test_loopback_only_no_dns(self):
        for host in ['localhost', 'example.com', '192.168.1.2', '0.0.0.0', 'https://127.0.0.1', '::', '::ffff:192.168.0.1', '::1%lo']:
            with self.subTest(host=host), patch.object(socket.socket, 'connect') as connect:
                with self.assertRaises(control.ControlError):
                    control.call_control(FakeStore(setting={'endpoint': {'host': host, 'port': 10}}), {'app': 'cadcraft', 'method': 'ping'})
                connect.assert_not_called()
        self.assertEqual(control._endpoint({'host': '::1', 'port': 5}), ('::1', 5))
        for port in [True, 0, -1, 65536, '10']:
            with self.assertRaises(control.ControlError):
                control._endpoint({'host': '127.0.0.1', 'port': port})

    def test_call_cannot_override_binding_or_roots(self):
        for key in ['endpoint', 'host', 'port', 'token_file', 'control_file', 'command', 'argv', 'read_root', 'write_root', 'transport']:
            with self.subTest(key=key), self.assertRaises(control.ControlError):
                control.call_control(FakeStore(), {'app': 'cadcraft', 'method': 'ping', key: 'override'})

    def test_foreign_platform_never_falls_back(self):
        with patch.object(control, 'native_platform', return_value='windows'), patch.object(socket.socket, 'connect') as connect:
            with self.assertRaisesRegex(control.ControlError, 'native host'):
                control.call_control(FakeStore(), {'app': 'cadcraft', 'method': 'ping', 'platform': 'mac'})
            connect.assert_not_called()

    def test_all_apps_exact_raw_data_and_vendor_errors(self):
        for app, profile in control.profiles().items():
            with self.subTest(app=app), tempfile.TemporaryDirectory() as folder:
                secret = 'synthetic-control-secret-0123456789'
                params = {'key': 'Enter', 'data': [False, None, {'x': 'ü'}]}
                expected = {'id': 2, 'ok': False, 'error': {'vendor': 'precise failure'}, 'extra': [1, None]}
                if app == 'pdfcraft':
                    expected = {'jsonrpc': '2.0', 'id': 2, 'error': {'code': -32000, 'message': 'vendor failure'}, 'extra': [1, None]}

                def handle(conn, reader):
                    req = json.loads(reader.readline())
                    if profile['auth'] in ('photo-token', 'pdf-token'):
                        self.assertEqual(req['method'], 'auth')
                        self.assertEqual(req['params'], {'token': secret})
                        if app == 'pdfcraft':
                            conn.sendall(b'{"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n')
                        else:
                            reply(conn, req, {})
                        req = json.loads(reader.readline())
                    self.assertEqual(req['method'], 'ui.future.method')
                    self.assertEqual(req['params'], params)
                    self.assertEqual(req.get('key'), secret if app == 'wordcraft' else None)
                    conn.sendall((json.dumps(expected) + '\n').encode())

                with server(handle) as endpoint:
                    setting = {'endpoint': endpoint, 'transport': 'tcp-jsonl'}
                    if app == 'pdfcraft':
                        setting.pop('endpoint')
                        setting['control_file'] = self.private(folder, 'control.json', json.dumps({'port': endpoint['port'], 'token': secret}))
                    if app in ('photocraft', 'wordcraft'):
                        setting['token_file' if app == 'photocraft' else 'key_file'] = self.private(folder, 'secret', secret)
                    result = control.call_control(FakeStore(app, setting), {'app': app, 'method': 'ui.future.method', 'params': params}, 2)
                    self.assertFalse(result['ok'])
                    self.assertEqual(result['response'], expected)
                    self.assertNotIn(secret, json.dumps(result))

    def test_named_control_is_operator_selection(self):
        def handle(conn, reader):
            reply(conn, json.loads(reader.readline()), ['unmodified', {'png': 'synthetic'}])
        with server(handle) as endpoint:
            store = FakeStore(setting={'named': {'window2': {'endpoint': endpoint}}})
            result = control.call_control(store, {'app': 'cadcraft', 'method': 'ui.screenshot', 'control_name': 'window2'})
            self.assertEqual(result['response']['result'], ['unmodified', {'png': 'synthetic'}])

    def test_invalid_responses(self):
        for data in [b'garbage\n', b'[]\n', b'{"id":2,"ok":true,"result":NaN}\n', b'{"id":2,"id":2,"ok":true}\n', b'{"id":9,"ok":true}\n', b'{"id":true,"ok":true}\n', b'{"ok":true}\n', b'{"id":2,"ok":"yes"}\n', b'\xff\n', b'{"id":2,"ok":true}\n{}\n', b'{"id":2,"ok":true}']:
            with self.subTest(data=data):
                def handle(conn, reader):
                    reader.readline()
                    conn.sendall(data)
                with server(handle) as endpoint, self.assertRaises(control.ControlError):
                    control.call_control(FakeStore(setting={'endpoint': endpoint}), {'app': 'cadcraft', 'method': 'ping'}, 1)

    def test_oversize_response(self):
        def handle(conn, reader):
            reader.readline()
            conn.sendall(b'x' * 101 + b'\n')
        with server(handle) as endpoint, patch.object(control, 'MAX_RESPONSE', 100), self.assertRaisesRegex(control.ControlError, 'size limit'):
            control.call_control(FakeStore(setting={'endpoint': endpoint}), {'app': 'cadcraft', 'method': 'ping'})

    def test_timeout_never_retries(self):
        seen = []
        def handle(conn, reader):
            seen.append(reader.readline())
            time.sleep(0.15)
        with server(handle) as endpoint, self.assertRaises(control.ControlError):
            control.call_control(FakeStore(setting={'endpoint': endpoint}), {'app': 'cadcraft', 'method': 'mutate'}, 0.04)
        self.assertEqual(len(seen), 1)

    def test_secret_echo_is_withheld(self):
        secret = 'synthetic-private-secret'
        def handle(conn, reader):
            req = json.loads(reader.readline())
            reply(conn, req, {'echo': secret})
        with tempfile.TemporaryDirectory() as folder, server(handle) as endpoint:
            setting = {'endpoint': endpoint, 'key_file': self.private(folder, 'key', secret)}
            with self.assertRaises(control.ControlError) as error:
                control.call_control(FakeStore('wordcraft', setting), {'app': 'wordcraft', 'method': 'ui.key', 'params': {'key': 'Enter'}})
            self.assertNotIn(secret, str(error.exception))

    def test_auth_failure_does_not_send_method(self):
        seen = []
        def handle(conn, reader):
            req = json.loads(reader.readline())
            seen.append(req)
            reply(conn, req, None, ok=False, error='unauthorized')
            self.assertEqual(reader.readline(), b'')
        with tempfile.TemporaryDirectory() as folder, server(handle) as endpoint:
            setting = {'endpoint': endpoint, 'transport': 'tcp-jsonl', 'token_file': self.private(folder, 'token', 'synthetic-secret')}
            with self.assertRaisesRegex(control.ControlError, 'authentication'):
                control.call_control(FakeStore('photocraft', setting), {'app': 'photocraft', 'method': 'ui.inspect'})
        self.assertEqual(len(seen), 1)

    def test_native_app_cli_argv_data_not_shell(self):
        for app in ['designcraft', 'deckcraft']:
            setting = {'endpoint': {'host': '127.0.0.1', 'port': 12345}}
            with patch.object(control, '_cli', return_value=['exact', None]) as cli:
                value = control.call_control(FakeStore(app, setting), {'app': app, 'method': 'ui.menu.list', 'params': {'text': '; not shell'}})
                self.assertEqual(cli.call_args.args[0][1:], ['app', '--port', '127.0.0.1:12345', '--method', 'ui.menu.list', '{"text":"; not shell"}'])
                self.assertEqual(value['response'], ['exact', None])

    def test_photo_native_bridge_full_raw_method(self):
        with tempfile.TemporaryDirectory() as folder:
            token = self.private(folder, 'token', 'synthetic-token')
            setting = {'endpoint': {'host': '127.0.0.1', 'port': 12345}, 'token_file': token}
            with patch.object(control, 'Session') as session:
                session.return_value.__enter__.return_value.rpc.return_value = {'content': [], 'isError': False}
                control.call_control(FakeStore('photocraft', setting), {'app': 'photocraft', 'method': 'ui.dialog.open', 'params': {'kind': 'about'}})
                self.assertEqual(session.call_args.args[1][1:], ['mcp', '--bridge', '127.0.0.1:12345', '--control-token-file', token])
                session.return_value.__enter__.return_value.rpc.assert_called_once_with('tools/call', {'name': 'control_call', 'arguments': {'method': 'ui.dialog.open', 'params': {'kind': 'about'}}})

    def test_pdf_native_key_value_and_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            file = self.private(folder, 'pdf.json', '{"port":12345,"token":"synthetic-token"}')
            store = FakeStore('pdfcraft', {'control_file': file})
            with patch.object(control, '_cli', return_value={'png_base64': 'synthetic'}) as cli:
                result = control.call_control(store, {'app': 'pdfcraft', 'method': 'ui.screenshot', 'params': {'path': 'x y.png'}})
                self.assertEqual(cli.call_args.args[0][1:], ['ui', '--control', file, 'ui.screenshot', 'path="x y.png"'])
                self.assertEqual(result['response'], {'png_base64': 'synthetic'})
            with patch.object(control, '_tcp', return_value={'jsonrpc': '2.0', 'id': 2, 'result': []}) as tcp:
                control.call_control(store, {'app': 'pdfcraft', 'method': 'ui.future', 'params': [1, None]})
                self.assertEqual(tcp.call_args.args[2], [1, None])

    def test_cli_real_synthetic_subprocess(self):
        result = control._cli([sys.executable, '-c', 'print(\'{"synthetic": [1, null]}\')'], time.monotonic() + 3)
        self.assertEqual(result, {'synthetic': [1, None]})
        for code in ['print("not JSON")', 'import sys; sys.exit(7)', 'import time; time.sleep(2)']:
            with self.assertRaises(control.ControlError):
                control._cli([sys.executable, '-c', code], time.monotonic() + 0.2)
        with patch.object(control, 'MAX_RESPONSE', 100), self.assertRaises(control.ControlError):
            control._cli([sys.executable, '-c', 'print("x"*1000)'], time.monotonic() + 3)

    def test_private_file_limits_and_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            file = self.private(folder, 'token', 'x' * 101)
            with patch.object(control, 'MAX_SECRET_FILE', 100), self.assertRaises(control.ControlError):
                control._private_file(file)
            if os.name != 'nt':
                os.chmod(file, 0o644)
                with self.assertRaises(control.ControlError):
                    control._private_file(file)
            for path in [folder, 'relative-token', str(Path(folder) / 'missing')]:
                with self.assertRaises(control.ControlError):
                    control._private_file(path)

    def test_invalid_requests_before_connection(self):
        for method in ['', None, '--port', 'ui.x\nnew', 'auth']:
            with self.assertRaises(control.ControlError):
                control.call_control(FakeStore(), {'app': 'cadcraft', 'method': method})
        for timeout in [0, -1, True, float('inf'), float('nan')]:
            with self.assertRaises(control.ControlError):
                control.call_control(FakeStore(), {'app': 'cadcraft', 'method': 'ping'}, timeout)
        for params in [{'x': float('nan')}, {1: 'not a JSON key'}, (1, 2), {'x': object()}]:
            with self.assertRaises(control.ControlError):
                control.call_control(FakeStore(), {'app': 'cadcraft', 'method': 'ping', 'params': params})
        with self.assertRaisesRegex(control.ControlError, 'Unsupported operator'):
            control.call_control(FakeStore(setting={'endpoint': {'host': '127.0.0.1', 'port': 12345}, 'read_root': '/override'}), {'app': 'cadcraft', 'method': 'ping'})


if __name__ == '__main__':
    unittest.main()
