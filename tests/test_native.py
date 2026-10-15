"""Synthetic native subprocess ownership/IO tests, never use real user applications."""
import ctypes,json,os
from pathlib import Path
import subprocess,sys,tempfile,time,unittest
from unittest.mock import patch
from art_cli.native import run
from art_cli.processes import OwnedPopen,OWNED_PROCESSES
from art_cli.rpc import RpcError

class NativeTests(unittest.TestCase):
    def test_stdin_roundtrip(self):
        result=run([sys.executable,'-c','import sys;sys.stdout.buffer.write(sys.stdin.buffer.read())'],input_text='ART äöü\n',timeout=5)
        self.assertEqual(result['exit_code'],0);self.assertEqual(result['stdout'],'ART äöü\n');self.assertFalse(OWNED_PROCESSES)
    def test_timeout_owned_cleanup(self):
        with self.assertRaises(RpcError) as caught:run([sys.executable,'-c','import time;time.sleep(20)'],timeout=.2)
        self.assertEqual(caught.exception.error['code'],-32012);self.assertFalse(OWNED_PROCESSES)
    def test_output_bound_during_process(self):
        with patch('art_cli.native.MAX_BYTES',512):
            with self.assertRaises(RpcError) as caught:run([sys.executable,'-c','import sys;sys.stdout.write("X"*2048)'],timeout=3)
        self.assertEqual(caught.exception.error['code'],-32017);self.assertFalse(OWNED_PROCESSES)
    def test_tree_cleanup_does_not_touch_unrelated_process(self):
        unrelated=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        command='import subprocess,sys,time;p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);print(p.pid,flush=True);time.sleep(30)'
        proc=OwnedPopen([sys.executable,'-c',command],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
        handle=None
        try:
            pid=int(proc.stdout.readline().strip())
            if os.name=='nt':
                kernel=ctypes.WinDLL('kernel32',use_last_error=True)
                kernel.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32];kernel.OpenProcess.restype=ctypes.c_void_p
                kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32];kernel.WaitForSingleObject.restype=ctypes.c_uint32
                kernel.CloseHandle.argtypes=[ctypes.c_void_p];handle=kernel.OpenProcess(0x00100000,False,pid)
                self.assertTrue(handle)
            proc.close_tree()
            if os.name=='nt':self.assertEqual(kernel.WaitForSingleObject(handle,3000),0)
            else:
                time.sleep(.1)
                state=subprocess.run(['/bin/ps','-p',str(pid),'-o','stat='],capture_output=True,text=True).stdout.strip()
                self.assertTrue(not state or state.startswith('Z'),state)
            self.assertIsNone(unrelated.poll())
        finally:
            proc.close_tree();proc.stdout.close()
            if handle:kernel.CloseHandle(handle)
            unrelated.kill();unrelated.wait()
        self.assertFalse(OWNED_PROCESSES)
    def test_catalog_cannot_create_owned_worker(self):
        from art_cli.api import dispatch
        with tempfile.TemporaryDirectory() as tmp,patch('art_cli.processes.OwnedPopen.__init__',side_effect=AssertionError('unexpected worker')):
            self.assertTrue(dispatch('catalog',{},home=Path(tmp))['ok'])

if __name__=='__main__':unittest.main()
