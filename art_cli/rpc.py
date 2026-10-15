"""Bounded stdio JSON-RPC transport, adapted from the existing Craft router.
No global workers. All subprocesses are owned by a context manager.
"""
import copy
import hashlib
import json
import math
import os
import queue
import subprocess
import threading
import weakref
from .processes import OwnedPopen,current_execution

ACTIVE_SESSIONS = weakref.WeakSet()
ACTIVE_LOCK = threading.RLock()

MAX_LINE = 64 * 1024 * 1024
MAX_PAGES = 1000

def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    def invalid(_):
        raise ValueError("non-finite JSON number")
    def finite_float(text):
        value = float(text)
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number")
        return value
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid, parse_float=finite_float)
    except RecursionError:
        raise ValueError("JSON nesting limit exceeded") from None


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def valid_id(value):
    return isinstance(value, (str, int)) and not isinstance(value, bool)


def id_key(value):
    return (type(value).__name__, value)


class RpcError(Exception):
    def __init__(self, code, message, data=None):
        self.error = {"code": code, "message": message}
        if data is not None:
            self.error["data"] = data
        super().__init__(message)


class CatalogError(ValueError):
    pass


class Child:
    def __init__(self, router, app, entry):
        self.router, self.app, self.entry = router, app, entry
        self.process = None
        self.serial = threading.Lock()
        self.outgoing = queue.Queue(maxsize=128)
        self.state_lock = threading.RLock()
        self.pending = {}
        self.next_id = 0
        self.started = False
        self.ready = False
        self.uncertain = False
        self.closed = False
        self.capabilities = {}

    def send(self, message):
        payload = (canonical(message) + "\n").encode("utf-8")
        if len(payload) > MAX_LINE:
            raise RpcError(-32602, "Request exceeds transport size limit")
        if self.closed or self.process is None or self.process.poll() is not None:
            raise RpcError(-32011, "Native child transport unavailable") from None
        try:
            self.outgoing.put_nowait(payload)
        except queue.Full:
            self.uncertain = True
            raise RpcError(-32017, "Native transport backpressure; state uncertain") from None

    def write_loop(self):
        try:
            while not self.closed:
                try:
                    payload = self.outgoing.get(timeout=0.2)
                except queue.Empty:
                    continue
                view = memoryview(payload)
                while view and not self.closed:
                    self.router.check_cancelled(None)
                    written = self.process.stdin.write(view)
                    if not written:
                        raise OSError()
                    view = view[written:]
        except (OSError, ValueError, RpcError):
            self.fail_transport()

    def fail_transport(self):
        with self.state_lock:
            self.uncertain = True
            for event, result in self.pending.values():
                if not event.is_set():
                    result.update(error={"code": -32011, "message": "Native child disconnected or violated protocol"})
                    event.set()

    def read_loop(self):
        try:
            while not self.closed:
                line = self.process.stdout.readline(MAX_LINE + 1)
                if not line:
                    break
                if len(line) > MAX_LINE or not line.endswith(b"\n"):
                    raise ValueError()
                message = strict_json(line.decode("utf-8"))
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    raise ValueError()
                if "method" in message:
                    if not isinstance(message["method"], str):
                        raise ValueError()
                    if "id" in message:
                        if not valid_id(message["id"]):
                            raise ValueError()
                        self.router.reverse_request(self, message)
                    else:
                        self.router.child_notification(self, message)
                else:
                    if not valid_id(message.get("id")) or (("result" in message) == ("error" in message)):
                        raise ValueError()
                    with self.state_lock:
                        waiter = self.pending.get(id_key(message["id"]))
                        if waiter:
                            waiter[1].update(message)
                            waiter[0].set()
        except (ValueError, UnicodeError, OSError, TypeError, KeyError, RpcError):
            pass  # Never print native payload, stderr, tool arguments or exception text.
        finally:
            self.fail_transport()

    def rpc(self, method, params=None, upstream_id=None):
        self.router.check_cancelled(upstream_id)
        with self.state_lock:
            self.next_id += 1
            request_id = self.next_id
            event, result = threading.Event(), {}
            self.pending[id_key(request_id)] = (event, result)
        try:
            request = {"jsonrpc": "2.0", "id": request_id, "method": method}
            if params is not None:
                request["params"] = params
            with self.router.lock:
                if upstream_id is not None:
                    self.router.check_cancelled(upstream_id)
                    self.router.bind_request(upstream_id, self, request_id)
                self.router.check_cancelled(upstream_id)
                self.send(request)
            while not event.wait(min(.05,self.router.execution.remaining())):
                self.router.check_cancelled(upstream_id)
            self.router.check_cancelled(upstream_id)
            if "error" in result:
                error = RpcError(-32603, "Native error")
                error.error = result["error"]  # Preserve exact downstream error including data.
                raise error
            return result["result"]
        finally:
            with self.state_lock:
                self.pending.pop(id_key(request_id), None)
            if upstream_id is not None:
                self.router.unbind_request(upstream_id)

    def initialize_native(self):
        if self.started or self.closed or self.router.closed:
            raise RpcError(-32013, "Native session unavailable; automatic restart is disabled")
        self.started = True
        kwargs = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL,
                  "shell": False, "bufsize": 0}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            # Lifecycle lock prevents EOF cleanup from racing a new Popen.
            with self.router.lifecycle_lock:
                self.router.check_cancelled(None)
                if self.router.closed:
                    raise OSError()
                self.process = OwnedPopen(self.entry["command"], execution=self.router.execution, **kwargs)
        except OSError:
            raise RpcError(-32010, "Native executable could not be started") from None
        threading.Thread(target=self.read_loop, daemon=True, name=f"{self.app}-reader").start()
        threading.Thread(target=self.write_loop, daemon=True, name=f"{self.app}-writer").start()
        native_initialize = copy.deepcopy(self.router.initialize_params)
        preferred_version = self.entry.get("protocolVersion", self.entry.get("protocol_version"))
        if preferred_version is not None:
            native_initialize["protocolVersion"] = preferred_version
        result = self.rpc("initialize", native_initialize)
        actual_version = result.get("protocolVersion") if isinstance(result, dict) else None
        expected_version = self.entry.get("protocolVersion", self.entry.get("protocol_version"))
        # Bridge the verified common JSON-RPC tool surface across supported MCP revisions.
        # Do not require all twelve native applications to negotiate the same revision.
        supported = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}
        if actual_version not in supported or (expected_version is not None and actual_version != expected_version):
            self.uncertain = True
            raise RpcError(-32015, "Child protocol differs from verified catalog; session retained")
        self.capabilities = result.get("capabilities", {})
        self.router.check_cancelled(None)
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def start(self):
        if self.ready:
            return
        self.initialize_native()
        actual = self.collect("tools/list", "tools")
        # Order is not semantic; every schema field and exact wire name is.
        expected = sorted(self.entry["tools"], key=lambda t: t["name"])
        if sorted(actual, key=lambda t: t["name"]) != expected:
            self.uncertain = True
            raise RpcError(-32014, "Frozen tool catalog differs from native session; recapture required",
                           {"app": self.app, "state": "catalog_mismatch"})
        self.ready = True

    def collect(self, method, field, params=None):
        items, seen, cursor = [], set(), None
        for _ in range(MAX_PAGES):
            args = copy.deepcopy(params or {})
            if cursor is not None:
                args["cursor"] = cursor
            page = self.rpc(method, args)
            if not isinstance(page, dict) or not isinstance(page.get(field), list):
                raise RpcError(-32011, "Invalid native list response")
            items.extend(page[field])
            cursor = page.get("nextCursor")
            if cursor is None:
                return items
            if not isinstance(cursor, str) or cursor in seen:
                raise RpcError(-32011, "Invalid native pagination")
            seen.add(cursor)
        raise RpcError(-32011, "Native pagination limit exceeded")

    def run(self, method, params=None, upstream_id=None, collection=None, capability=None):
        if not self.serial.acquire(timeout=self.router.timeout):
            raise RpcError(-32016, "App queue wait timed out; request was not dispatched")
        try:
            if upstream_id is not None:
                self.router.check_cancelled(upstream_id)
            if self.uncertain:
                raise RpcError(-32013, "App state uncertain; session retained; automatic retry disabled")
            self.start()
            if capability and capability not in self.capabilities:
                if collection:
                    return []
                raise RpcError(-32601, "Native app does not advertise this capability")
            if collection:
                return self.collect(method, collection, params)
            return self.rpc(method, params, upstream_id)
        finally:
            self.serial.release()

    def close(self):
        self.closed = True
        process = self.process
        if process is None:
            return
        # Terminate the owned tree before touching pipes: a blocked writer must
        # not hold stream.close() hostage during cancellation or worker EOF.
        process.close_tree()
        self.fail_transport()
        for stream in (process.stdout, process.stdin):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        process.close_tree()



class Session:
    """One owned native JSON-RPC session, live schema discovery not a frozen gate."""
    def __init__(self, app, command, timeout=60):
        self.app=app
        self.timeout=timeout
        self.execution=current_execution(timeout)
        self.closed=False
        self.lock=threading.RLock()
        self.lifecycle_lock=threading.RLock()
        self.initialize_params={"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"art-cli","version":"0.2.0"}}
        self.child=Child(self,app,{"command":command})
        self.info=None
        self.notifications=[]

    def __enter__(self):
        try:
            with ACTIVE_LOCK:ACTIVE_SESSIONS.add(self)
            self.info=self.child.initialize_native()
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self,*exc):self.close()
    def close(self):
        with self.lifecycle_lock:
            self.closed=True
            self.child.close()
        with ACTIVE_LOCK:ACTIVE_SESSIONS.discard(self)
    def check_cancelled(self,request_id):
        self.execution.remaining()
        if self.closed:raise RpcError(-32800,"Operation cancelled; completion uncertain")
    def bind_request(self,*args):pass
    def unbind_request(self,*args):pass
    def child_notification(self,child,message):
        if len(self.notifications)<32:self.notifications.append(message)
    def reverse_request(self,child,message):
        if message["method"]=="ping":
            child.send({"jsonrpc":"2.0","id":message["id"],"result":{}})
        else:
            child.send({"jsonrpc":"2.0","id":message["id"],"error":{"code":-32601,"message":"ART-CLI has no interactive approval/sampling client; user action required"}})
    def rpc(self,method,params=None):return self.child.rpc(method,params)
    def collect(self,method,field,params=None):return self.child.collect(method,field,params)
