"""Regression tests for untrusted IDs, using an isolated real worker process."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import unittest

ROOT = Path(os.environ.get('ART_TEST_ROOT', Path(__file__).resolve().parents[1]))


class WorkerIdTests(unittest.TestCase):
    def setUp(self):
        code = (
            'import sys;sys.path.insert(0,sys.argv[1]);'
            'import art_cli.worker as w;'
            'w.dispatch=lambda operation,args,**kw: '
            '{"ok":True,"cancelled":kw["cancel_event"].wait(5)};'
            'w.serve(heartbeat_interval=.05,heartbeat_timeout=.4)'
        )
        self.process = subprocess.Popen(
            [sys.executable, '-c', code, str(ROOT)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.messages = queue.Queue()
        def read():
            for line in self.process.stdout:
                self.messages.put(json.loads(line))
            self.messages.put(None)
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        self.send({'jsonrpc': '2.0', 'id': 0, 'method': 'initialize'})
        self.assertIn('result', self.receive())

    def tearDown(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=4)
        self.reader.join(timeout=2)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if not stream.closed:
                stream.close()

    def send(self, value):
        self.process.stdin.write(json.dumps(value) + '\n')
        self.process.stdin.flush()

    def receive(self, acknowledge=True):
        while True:
            value = self.messages.get(timeout=3)
            self.assertIsNotNone(value, 'worker terminated instead of rejecting invalid ID')
            if acknowledge and value.get('method') == 'ping':
                self.send({'jsonrpc': '2.0', 'id': value['id'], 'result': {}})
                continue
            return value

    def test_invalid_cancellation_ids_do_not_crash_or_cancel_other_request(self):
        self.send({'jsonrpc': '2.0', 'id': 1, 'method': 'art/dispatch',
                   'params': {'operation': 'guide'}})
        for invalid in ([], {}, True, False, None, 1.0):
            self.send({'jsonrpc': '2.0', 'method': 'notifications/cancelled',
                       'params': {'requestId': invalid}})
        self.send({'jsonrpc': '2.0', 'id': 2, 'method': 'art/dispatch',
                   'params': {'operation': 'guide'}})
        busy = self.receive()
        self.assertEqual(busy['id'], 2)
        self.assertEqual(busy['error']['code'], -32016)
        self.send({'jsonrpc': '2.0', 'method': 'notifications/cancelled',
                   'params': {'requestId': 1}})
        result = self.receive()
        self.assertEqual(result['id'], 1)
        self.assertTrue(result['result']['cancelled'])
        self.send({'jsonrpc': '2.0', 'id': 'alive', 'method': 'ping'})
        self.assertEqual(self.receive()['id'], 'alive')

    def test_invalid_response_ids_with_pending_heartbeat_do_not_crash(self):
        ping = self.receive(acknowledge=False)
        self.assertEqual(ping['method'], 'ping')
        for invalid in ([], {}, True, False, None, 1.0):
            self.send({'jsonrpc': '2.0', 'id': invalid, 'result': {}})
        self.send({'jsonrpc': '2.0', 'id': ping['id'], 'result': {}})
        # Continue beyond the heartbeat deadline while acknowledging valid pings.
        until = time.monotonic() + .6
        while time.monotonic() < until:
            self.send({'jsonrpc': '2.0', 'id': 'alive', 'method': 'ping'})
            self.assertEqual(self.receive()['id'], 'alive')
            time.sleep(.025)
        self.assertIsNone(self.process.poll())


if __name__ == '__main__':
    unittest.main()
