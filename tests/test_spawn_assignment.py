"""Native Windows scheduling regressions: no application code before ownership."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from art_cli.processes import OwnedPopen, ExecutionContext, OWNED_PROCESSES


@unittest.skipUnless(os.name == 'nt', 'Windows suspended creation and Job Objects')
class SpawnAssignmentTests(unittest.TestCase):
    def setUp(self):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        for name, args, result in [
            ('OpenProcess', [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            ('WaitForSingleObject', [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            ('TerminateProcess', [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            ('CloseHandle', [wintypes.HANDLE], wintypes.BOOL),
        ]:
            fn = getattr(self.kernel, name)
            fn.argtypes, fn.restype = args, result

    def open_process(self, pid):
        handle = self.kernel.OpenProcess(0x100001, False, pid)
        self.assertTrue(handle)
        return handle

    def stop_handle(self, handle):
        if self.kernel.WaitForSingleObject(handle, 0) == 0x102:
            self.assertTrue(self.kernel.TerminateProcess(handle, 1))
        self.assertEqual(self.kernel.WaitForSingleObject(handle, 5000), 0)
        self.kernel.CloseHandle(handle)

    def exercise(self, failure=False, cancel=False):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'app-started'
            grand = Path(folder) / 'grandchild'
            code = ('from pathlib import Path;import subprocess,sys,time;'
                    f'Path({str(marker)!r}).write_text("started");'
                    'p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"],'
                    'stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);'
                    f'Path({str(grand)!r}).write_text(str(p.pid));time.sleep(30)')
            import threading
            event = threading.Event()
            observed = {}
            test = self
            class Probe(OwnedPopen):
                def _prepare_job(self):
                    super()._prepare_job()
                    real, job = self._art_job
                    class Proxy:
                        def __getattr__(self, name):
                            return getattr(real, name)
                        def AssignProcessToJobObject(self, job, handle):
                            observed['process'] = test.open_process(self_process.pid)
                            # A real scheduling opportunity, before REAL assignment.
                            time.sleep(0.5)
                            observed['ran_before_assignment'] = marker.exists() or grand.exists()
                            if cancel:
                                event.set()
                            return False if failure else real.AssignProcessToJobObject(job, handle)
                    self_process = self
                    self._art_job = (Proxy(), job)
            unrelated = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(30)'])
            other_handle = self.open_process(unrelated.pid)
            process = None
            grand_handle = None
            try:
                if failure or cancel:
                    with self.assertRaises(Exception):
                        Probe([sys.executable, '-c', code], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              execution=ExecutionContext(10, event))
                else:
                    process = Probe([sys.executable, '-c', code])
                    end = time.monotonic() + 5
                    while (not grand.exists() or not grand.read_text()) and time.monotonic() < end:
                        time.sleep(0.01)
                    self.assertTrue(grand.exists(), 'child did not execute after resume')
                    grand_handle = self.open_process(int(grand.read_text()))
                    self.assertIn(process, OWNED_PROCESSES)
                    process.close_tree()
                    self.assertEqual(self.kernel.WaitForSingleObject(grand_handle, 5000), 0)
                self.assertFalse(observed['ran_before_assignment'])
                self.assertEqual(self.kernel.WaitForSingleObject(observed['process'], 5000), 0)
                if failure or cancel:
                    self.assertFalse(marker.exists())
                    self.assertFalse(grand.exists())
                self.assertEqual(self.kernel.WaitForSingleObject(other_handle, 0), 0x102)
            finally:
                if process is not None:
                    process.close_tree()
                # Also clean up an escaped synthetic grandchild when testing old code.
                if grand_handle is None and grand.exists() and grand.read_text():
                    grand_handle = self.open_process(int(grand.read_text()))
                if grand_handle:
                    self.stop_handle(grand_handle)
                if observed.get('process'):
                    self.stop_handle(observed['process'])
                self.stop_handle(other_handle)
                unrelated.wait(timeout=5)

    def test_discovery_and_resume_failures_close_all_owned_resources(self):
        from unittest.mock import patch
        real_loader = ctypes.WinDLL
        for failing_api in ('Thread32First', 'OpenThread', 'GetProcessIdOfThread', 'ResumeThread'):
            with self.subTest(api=failing_api), tempfile.TemporaryDirectory() as folder:
                marker = Path(folder) / 'must-not-run'
                instances = []
                handles = []
                test = self
                class Probe(OwnedPopen):
                    def _prepare_job(self):
                        instances.append(self)
                        super()._prepare_job()
                    def _resume_initial_thread(self, execution):
                        handles.append(test.open_process(self.pid))
                        return super()._resume_initial_thread(execution)
                class Library:
                    def __init__(self, *args, **kwargs):
                        self.real = real_loader(*args, **kwargs)
                    def __getattr__(self, name):
                        if name == failing_api:
                            def fail(*args):
                                ctypes.set_last_error(5)
                                return 0xffffffff if name == 'ResumeThread' else 0
                            setattr(self, name, fail)
                            return fail
                        return getattr(self.real, name)
                try:
                    with patch('ctypes.WinDLL', Library), self.assertRaises(OSError):
                        Probe([sys.executable, '-c', f'from pathlib import Path;Path({str(marker)!r}).touch()'],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    self.assertFalse(marker.exists())
                    self.assertEqual(self.kernel.WaitForSingleObject(handles[0], 5000), 0)
                    proc = instances[0]
                    self.assertNotIn(proc, OWNED_PROCESSES)
                    self.assertIsNone(proc._art_job)
                    self.assertTrue(all(s.closed for s in (proc.stdin, proc.stdout, proc.stderr)))
                finally:
                    for handle in handles:
                        self.stop_handle(handle)

    def test_direct_creation_failure_closes_job(self):
        instances = []
        class Probe(OwnedPopen):
            def _prepare_job(self):
                instances.append(self)
                super()._prepare_job()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(OSError):
                Probe([str(Path(folder) / 'missing.exe')], stdin=subprocess.PIPE,
                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertIsNone(instances[0]._art_job)
        self.assertNotIn(instances[0], OWNED_PROCESSES)

    def test_no_code_before_assignment_and_descendant_owned_after_resume(self):
        self.exercise()

    def test_assignment_failure_never_executes_application(self):
        self.exercise(failure=True)

    def test_cancellation_before_resume_never_executes_application(self):
        self.exercise(cancel=True)
