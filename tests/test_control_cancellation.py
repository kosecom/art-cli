"""Cancellation tests use only synthetic peers and temporary fake credentials."""
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
from art_cli.processes import CURRENT_EXECUTION, ExecutionContext
from test_control import FakeStore


def server(handler):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    listener.settimeout(2)
    port = listener.getsockname()[1]
    def run():
        try:
            with listener.accept()[0] as conn:
                conn.settimeout(2)
                handler(conn)
        finally:
            listener.close()
    thread = threading.Thread(target=run)
    thread.start()
    return port, thread


def reply(result):
    return (json.dumps({'id': 2, 'ok': True, 'result': result}) + '\n').encode()


class ControlCancellationTests(unittest.TestCase):
    def test_cancel_before_or_during_credentials_never_connects(self):
        for preset in (True, False):
            with self.subTest(preset=preset), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'fake-key'
                path.write_text('generated-test-key', encoding='utf-8')
                os.chmod(path, 0o600)
                event = threading.Event()
                if preset:
                    event.set()
                original = control._private_file
                def read(value):
                    result = original(value)
                    event.set()
                    return result
                store = FakeStore('wordcraft', {'endpoint': {'host': '127.0.0.1', 'port': 12345}, 'key_file': str(path)})
                token = CURRENT_EXECUTION.set(ExecutionContext(2, event))
                try:
                    with patch.object(control, '_private_file', side_effect=read), patch.object(socket, 'socket') as connect:
                        with self.assertRaisesRegex(control.ControlError, 'cancel'):
                            control.call_control(store, {'app': 'wordcraft', 'method': 'mutate'}, timeout=0.1)
                        connect.assert_not_called()
                finally:
                    CURRENT_EXECUTION.reset(token)
    def test_cancel_idle_tcp_is_prompt_and_never_retried(self):
        event = threading.Event()
        requests = []
        def handler(conn):
            requests.append(conn.recv(65536))
            event.set()
            time.sleep(0.8)
            try:
                conn.sendall(reply({'late': True}))
            except OSError:
                pass
        port, thread = server(handler)
        token = CURRENT_EXECUTION.set(ExecutionContext(2, event))
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(control.ControlError, 'cancel.*no retry'):
                control.call_control(FakeStore('cadcraft', {'transport': 'tcp-jsonl', 'endpoint': {'host': '127.0.0.1', 'port': port}}),
                                     {'app': 'cadcraft', 'method': 'mutate'})
            self.assertLess(time.monotonic() - started, 0.5)
        finally:
            CURRENT_EXECUTION.reset(token)
            thread.join(2)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].count(b'"method":"mutate"'), 1)

    def test_cancel_cli_wait_closes_owned_process(self):
        event = threading.Event()
        spawned = []
        real_popen = control.OwnedPopen
        def spawn(*args, **kwargs):
            process = real_popen([sys.executable, '-c', 'import time;time.sleep(2);print("{}")'], **kwargs)
            spawned.append(process)
            threading.Timer(0.15, event.set).start()
            return process
        token = CURRENT_EXECUTION.set(ExecutionContext(2, event))
        started = time.monotonic()
        try:
            store = FakeStore('designcraft', {'endpoint': {'host': '127.0.0.1', 'port': 12345}})
            with patch.object(control, 'OwnedPopen', side_effect=spawn):
                with self.assertRaisesRegex(control.ControlError, 'cancel.*no retry'):
                    control.call_control(store, {'app': 'designcraft', 'method': 'ui.mutate'})
            self.assertLess(time.monotonic() - started, 0.7)
            self.assertEqual(len(spawned), 1)
            self.assertIsNotNone(spawned[0].poll())
            self.assertTrue(spawned[0]._art_tree_closed)
        finally:
            CURRENT_EXECUTION.reset(token)
            for process in spawned:
                process.close_tree()

    def test_api_reports_cancelled_credentials_as_uncertain(self):
        from art_cli.api import dispatch
        from art_cli.config import Store
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'key'
            path.write_text('generated-test-key', encoding='utf-8')
            os.chmod(path, 0o600)
            event = threading.Event()
            config = {'apps': {'wordcraft': {'control': {'endpoint': {'host': '127.0.0.1', 'port': 12345}, 'key_file': str(path)}}}}
            store = Store(Path(folder))
            store.config = config
            original = control._private_file
            def read(value):
                text = original(value)
                event.set()
                return text
            with patch('art_cli.api.Store', return_value=store), patch.object(control, '_private_file', side_effect=read), patch.object(socket, 'socket') as connect:
                result = dispatch('control', {'app': 'wordcraft', 'method': 'mutate'}, home=Path(folder), cancel_event=event)
                connect.assert_not_called()
            self.assertFalse(result['ok'])
            self.assertEqual(result['error']['code'], -32800)
            self.assertEqual(result['completion'], 'uncertain')
            self.assertIn('no retry', result['error']['message'])

    def test_cancel_after_auth_reply_sends_no_mutation(self):
        event = threading.Event()
        requests = []
        after_auth = []
        def handler(conn):
            with conn.makefile('rb') as reader:
                request = json.loads(reader.readline())
                requests.append(request['method'])
                event.set()
                conn.sendall((json.dumps({'id': request['id'], 'ok': True}) + '\n').encode())
                try:
                    after_auth.append(reader.readline())
                except ConnectionResetError:
                    after_auth.append(b'')  # Windows closes unread auth replies with RST.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'token'
            path.write_text('generated-test-token', encoding='utf-8')
            os.chmod(path, 0o600)
            port, thread = server(handler)
            token = CURRENT_EXECUTION.set(ExecutionContext(2, event))
            try:
                store = FakeStore('photocraft', {'transport': 'tcp-jsonl', 'endpoint': {'host': '127.0.0.1', 'port': port}, 'token_file': str(path)})
                with self.assertRaisesRegex(control.ControlError, 'cancel.*no retry'):
                    control.call_control(store, {'app': 'photocraft', 'method': 'mutate'})
            finally:
                CURRENT_EXECUTION.reset(token)
                thread.join(2)
        self.assertEqual(requests, ['auth'])
        self.assertEqual(after_auth, [b''])

    def test_shared_total_deadline_includes_prepare_auth_and_receive(self):
        for inherited in (True, False):
            with self.subTest(inherited=inherited), tempfile.TemporaryDirectory() as folder:
                key = Path(folder) / 'key'
                key.write_text('temporary-generated-key', encoding='utf-8')
                os.chmod(key, 0o600)
                def handler(conn):
                    conn.recv(65536)
                    time.sleep(0.3)
                    try:
                        conn.sendall(reply({'late': True}))
                    except OSError:
                        pass
                port, thread = server(handler)
                store = FakeStore('wordcraft', {'endpoint': {'host': '127.0.0.1', 'port': port}, 'key_file': str(key)})
                read = control._private_file
                original_profiles = control.profiles
                def delayed_prepare():
                    time.sleep(0.12)
                    return original_profiles()
                def delayed_read(path):
                    time.sleep(0.12)
                    return read(path)
                token = CURRENT_EXECUTION.set(ExecutionContext(0.4)) if inherited else None
                started = time.monotonic()
                try:
                    with patch.object(control, 'profiles', side_effect=delayed_prepare), patch.object(control, '_private_file', side_effect=delayed_read):
                        with self.assertRaisesRegex(control.ControlError, 'timeout.*no retry'):
                            control.call_control(store, {'app': 'wordcraft', 'method': 'mutate'}, timeout=3 if inherited else 0.4)
                    self.assertLess(time.monotonic() - started, 0.52)
                finally:
                    if token is not None:
                        CURRENT_EXECUTION.reset(token)
                    thread.join(2)


if __name__ == '__main__':
    unittest.main()
