"""Executable stage-1 runtime regressions, isolated synthetic processes only."""
import ctypes
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from art_cli.api import dispatch
from art_cli.config import Store
from art_cli.native import run
from art_cli.processes import OWNED_PROCESSES, CURRENT_EXECUTION, ExecutionContext, OwnedPopen
from art_cli.rpc import RpcError

ROOT = Path(__file__).resolve().parents[1]
PEER = Path(__file__).with_name('runtime_peer.py')


def wait_file(path, timeout=5):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size:
            return path.read_text()
        time.sleep(.01)
    raise AssertionError('Synthetic peer failed to signal readiness: '+str(path))


class RuntimeReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def command(self, delay=.0, pages=1):
        return [sys.executable, str(PEER), 'rpc', str(self.home), str(delay), str(pages)]

    def test_precancel_every_operation_no_store_spawn_or_connect(self):
        event = threading.Event(); event.set()
        ops = ['catalog','doctor','guide','refresh','search','describe','execute','batch','rpc','native','control']
        with patch('art_cli.api.Store',side_effect=AssertionError('configuration accessed')), patch('socket.socket',side_effect=AssertionError('connected')):
            for operation in ops:
                for extra in ({}, {'platform':'mac'}, {'transport':'control'}):
                    with self.subTest(operation=operation,extra=extra):
                        result = dispatch(operation, {'app':'figcraft',**extra}, home=self.home, cancel_event=event)
                        self.assertFalse(result['ok'])
                        self.assertEqual(result['error']['code'],-32800)

    def test_cancel_after_route_lookup_prevents_control_and_remote_io(self):
        for remote in (False,True):
            with self.subTest(remote=remote):
                event=threading.Event()
                def route(*args):
                    event.set()
                    return {'command':self.command(),'platform':'mac'} if remote else None
                with patch.object(Store,'route',side_effect=route),patch('socket.socket',side_effect=AssertionError('connected')),patch('art_cli.rpc.OwnedPopen',side_effect=AssertionError('spawned')):
                    result=dispatch('control',{'app':'figcraft','method':'status','platform':'mac' if remote else 'local'},home=self.home,cancel_event=event)
                self.assertEqual(result['error']['code'],-32800)

    def test_cancel_after_executable_lookup_prevents_native_spawn(self):
        event=threading.Event()
        def executable(*args):
            event.set();return Path(sys.executable)
        with patch.object(Store,'executable',side_effect=executable),patch('art_cli.native.OwnedPopen',side_effect=AssertionError('spawned')):
            result=dispatch('native',{'app':'figcraft','argv':['-c','pass']},home=self.home,cancel_event=event)
        self.assertEqual(result['error']['code'],-32800)

    def test_direct_native_precancel_no_spawn(self):
        event = threading.Event(); event.set()
        with patch('art_cli.native.OwnedPopen',side_effect=AssertionError('spawned')):
            with self.assertRaises(RpcError) as caught:
                run([sys.executable,'-c','pass'],cancel_event=event)
        self.assertEqual(caught.exception.error['code'],-32800)

    def test_per_app_catalog_and_doctor_cache_only(self):
        with patch.object(Store,'command',side_effect=AssertionError('discovery')):
            for operation in ('catalog','doctor'):
                result=dispatch(operation,{'app':'figcraft'},home=self.home)
                self.assertTrue(result['ok']); self.assertFalse(result['worker_started'])
                self.assertEqual(result['metadata'],'not_cached_or_changed')

    def test_cancel_during_initialize_no_next_protocol_request(self):
        event=threading.Event()
        def cancel():
            wait_file(self.home/'requests'); event.set()
        thread=threading.Thread(target=cancel); thread.start()
        start=time.monotonic()
        with patch.object(Store,'command',return_value=self.command(2)):
            result=dispatch('rpc',{'app':'figcraft','method':'ping','timeout':5},home=self.home,cancel_event=event)
        thread.join(5)
        self.assertEqual(result['error']['code'],-32800)
        self.assertLess(time.monotonic()-start,1.5)
        self.assertEqual((self.home/'requests').read_text().splitlines(),['initialize'])
        self.assertFalse(OWNED_PROCESSES)

    def test_cold_search_describe_and_remote_cancel_initialization(self):
        cases=[('search',{'app':'figcraft'},False),('describe',{'app':'figcraft','tool':'absent'},False),('rpc',{'platform':'mac','app':'figcraft','method':'ping'},True)]
        for operation,args,remote in cases:
            with self.subTest(operation=operation):
                (self.home/'requests').unlink(missing_ok=True)
                event=threading.Event()
                def cancel():
                    wait_file(self.home/'requests');event.set()
                thread=threading.Thread(target=cancel);thread.start()
                route={'command':self.command(2),'platform':'mac'} if remote else None
                with patch.object(Store,'command',return_value=self.command(2)),patch.object(Store,'route',return_value=route):
                    result=dispatch(operation,args,home=self.home,cancel_event=event)
                thread.join(5)
                self.assertEqual(result['error']['code'],-32800)
                self.assertEqual((self.home/'requests').read_text().splitlines(),['initialize'])
                self.assertFalse(OWNED_PROCESSES)

    def test_finite_slow_pagination_obeys_total_deadline(self):
        start=time.monotonic()
        with patch.object(Store,'command',return_value=self.command(.24,8)):
            result=dispatch('refresh',{'app':'figcraft','commands':False,'timeout':1},home=self.home)
        self.assertFalse(result['ok'])
        self.assertEqual(result['apps'][0]['error']['code'],-32012)
        self.assertLess(time.monotonic()-start,1.7)
        self.assertLess((self.home/'requests').read_text().count('tools/list'),8)
        self.assertFalse(OWNED_PROCESSES)

    def test_refresh_metadata_and_command_discovery_share_budget(self):
        def slow_commands(*args,**kwargs):
            return run([sys.executable,'-c','import time;time.sleep(.7)'],timeout=5)
        start=time.monotonic()
        with patch.object(Store,'command',return_value=self.command(.25)), patch('art_cli.api.command_catalog',side_effect=slow_commands):
            result=dispatch('refresh',{'app':'figcraft','timeout':1},home=self.home)
        self.assertEqual(result['apps'][0]['error']['code'],-32012)
        self.assertLess(time.monotonic()-start,1.7)
        self.assertFalse(OWNED_PROCESSES)

    def test_native_stdin_and_mcp_data_passthrough(self):
        code='import json,sys;print(json.dumps([sys.argv[1:],sys.stdin.buffer.read().decode("utf-8")],ensure_ascii=True))'
        with patch.object(Store,'executable',return_value=Path(sys.executable)):
            result=dispatch('native',{'app':'figcraft','argv':['-c',code,'mcp','literal;data'],'stdin':'ä\nstdin','timeout':5},home=self.home)
        self.assertTrue(result['ok'],result)
        self.assertEqual(json.loads(result['stdout']),[['mcp','literal;data'],'ä\nstdin'])

    def test_shutdown_fence_rejects_late_spawn(self):
        # Isolated subprocess: the worker shutdown fence is intentionally permanent.
        code='from art_cli.processes import shutdown_owned,OwnedPopen; from art_cli.rpc import RpcError; import sys; shutdown_owned();\ntry: OwnedPopen([sys.executable,"-c","pass"])\nexcept RpcError as e: print(e.error["code"])\nelse: raise AssertionError("spawned")'
        result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'-32800')

    def worker(self,kind='worker'):
        # -c keeps package root importable without reading any installed profile.
        code='import runpy,sys;sys.argv='+repr([str(PEER),kind,str(self.home)])+';runpy.run_path('+repr(str(PEER))+',run_name="__main__")'
        proc=subprocess.Popen([sys.executable,'-c',code],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.addCleanup(self.cleanup_worker,proc)
        frames=queue.Queue()
        def read():
            for line in proc.stdout:frames.put(json.loads(line))
        threading.Thread(target=read,daemon=True).start()
        self.send(proc,1,'initialize',{})
        self.assertEqual(frames.get(timeout=5)['id'],1)
        return proc,frames

    @staticmethod
    def cleanup_worker(proc):
        if proc.poll() is None:proc.kill()
        proc.wait(timeout=5)
        for stream in (proc.stdin,proc.stdout,proc.stderr):
            if stream:stream.close()

    @staticmethod
    def send(proc,ident,method,params):
        proc.stdin.write(json.dumps({'jsonrpc':'2.0','id':ident,'method':method,'params':params})+'\n');proc.stdin.flush()

    def native_job(self,proc):
        self.send(proc,2,'art/dispatch',{'operation':'native','arguments':{'app':'figcraft','argv':[str(PEER),'child',str(self.home)],'timeout':20}})

    def process_handle(self,pid):
        if os.name!='nt':return None
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32];kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32];kernel.WaitForSingleObject.restype=ctypes.c_uint32
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.OpenProcess(0x00100000,False,pid)
        self.assertTrue(handle)
        self.addCleanup(kernel.CloseHandle,handle)
        return kernel,handle

    def assert_dead(self,pid,handle):
        if handle:
            kernel,h=handle; self.assertEqual(kernel.WaitForSingleObject(h,3000),0)
        else:
            state=subprocess.run(['/bin/ps','-p',str(pid),'-o','stat='],capture_output=True,text=True).stdout.strip()
            self.assertTrue(not state or state.startswith('Z'),state)

    def test_worker_eof_kills_actual_native_child(self):
        proc,_=self.worker(); self.native_job(proc)
        pid=int(wait_file(self.home/'pid')); handle=self.process_handle(pid)
        proc.stdin.close(); self.assertEqual(proc.wait(timeout=6),0)
        self.assert_dead(pid,handle)

    def test_heartbeat_loss_kills_actual_native_child(self):
        proc,_=self.worker(); self.native_job(proc)
        pid=int(wait_file(self.home/'pid')); handle=self.process_handle(pid)
        self.assertEqual(proc.wait(timeout=6),3)
        self.assert_dead(pid,handle)

    def test_worker_eof_prevents_late_spawn(self):
        proc,_=self.worker('worker-late'); self.native_job(proc)
        wait_file(self.home/'ready'); proc.stdin.close()
        self.assertEqual(proc.wait(timeout=6),0)
        self.assertFalse((self.home/'pid').exists())


if __name__=='__main__':unittest.main()
