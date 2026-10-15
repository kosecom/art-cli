"""Ownership of native worker process trees; never target pre-existing GUIs."""
import os
import signal
import subprocess
import threading
import weakref
import time
from contextvars import ContextVar

OWNED_PROCESSES=weakref.WeakSet()
OWNED_LOCK=threading.RLock()
SHUTTING_DOWN=False
CURRENT_EXECUTION=ContextVar('art_execution',default=None)


class ExecutionContext:
    """One absolute budget across discovery, initialization and execution.

    Control transports can use current_execution().remaining() before each I/O;
    capture this object explicitly when handing work to a reader/writer thread.
    """
    def __init__(self,timeout,cancel_event=None):
        self.deadline=time.monotonic()+timeout
        self.cancel_event=cancel_event

    def remaining(self):
        from .rpc import RpcError
        if SHUTTING_DOWN or (self.cancel_event is not None and self.cancel_event.is_set()):
            raise RpcError(-32800,'Operation cancelled; completion uncertain; no retry')
        left=self.deadline-time.monotonic()
        if left<=0:raise RpcError(-32012,'Job deadline exceeded; completion uncertain; no retry')
        return left


def current_execution(timeout=120,cancel_event=None):
    return CURRENT_EXECUTION.get() or ExecutionContext(timeout,cancel_event)


def shutdown_owned():
    """Dedicated worker shutdown fence, serialized with spawn AND registration."""
    global SHUTTING_DOWN
    with OWNED_LOCK:
        SHUTTING_DOWN=True
        processes=list(OWNED_PROCESSES)
    for process in processes:process.close_tree()

class OwnedPopen(subprocess.Popen):
    """A private process group (macOS) / kill-on-close Job Object (Windows)."""
    def __init__(self,*args,**kwargs):
        # No shutdown snapshot can miss a process between creation and ownership.
        execution=kwargs.pop('execution',None) or current_execution()
        with OWNED_LOCK:
            execution.remaining()
            self._spawn(*args,execution=execution,**kwargs)

    def _spawn(self,*args,execution,**kwargs):
        self._art_job=None;self._art_tree_closed=False;self._art_guard=threading.RLock()
        try:
            if os.name=='nt':
                # Keep stdlib argv/stdio behavior, but forbid code before ownership.
                kwargs['creationflags']=kwargs.get('creationflags',0)|subprocess.CREATE_NO_WINDOW|0x4  # CREATE_SUSPENDED
                self._prepare_job()
            else:kwargs['start_new_session']=True
            super().__init__(*args,**kwargs)
        except BaseException:
            if self._art_job is not None:
                kernel,handle=self._art_job;kernel.CloseHandle(handle);self._art_job=None
            raise
        try:
            if os.name=='nt':
                kernel,handle=self._art_job
                if not kernel.AssignProcessToJobObject(handle,int(self._handle)):raise OSError('Could not assign native worker ownership; refusing unmanaged execution')
            with OWNED_LOCK:OWNED_PROCESSES.add(self)
            if os.name=='nt':self._resume_initial_thread(execution)
        except BaseException:
            try:
                if self.poll() is None:super().kill();self.wait()
            finally:
                try:self.close_tree()
                finally:
                    # Failed constructors have no caller to close these streams.
                    for stream in (self.stdin,self.stdout,self.stderr):
                        if stream is not None:stream.close()
                    if os.name=='nt':self._handle.Close()
            raise

    def _resume_initial_thread(self,execution):
        """Reacquire only our suspended initial thread via documented Win32 APIs.

        Popen closes CreateProcess's thread handle. Toolhelp supplies its ID;
        verify the opened thread against our live process handle before resuming.
        Ambiguous/missing threads fail closed, never a process-wide resume.
        No debug privilege, global monkeypatch or CPython implementation copy.
        """
        import ctypes
        from ctypes import wintypes
        class ThreadEntry(ctypes.Structure):
            _fields_=[('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),
                      ('th32ThreadID',wintypes.DWORD),('th32OwnerProcessID',wintypes.DWORD),
                      ('tpBasePri',wintypes.LONG),('tpDeltaPri',wintypes.LONG),('dwFlags',wintypes.DWORD)]
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        signatures={
            'CreateToolhelp32Snapshot':([wintypes.DWORD,wintypes.DWORD],wintypes.HANDLE),
            'Thread32First':([wintypes.HANDLE,ctypes.POINTER(ThreadEntry)],wintypes.BOOL),
            'Thread32Next':([wintypes.HANDLE,ctypes.POINTER(ThreadEntry)],wintypes.BOOL),
            'OpenThread':([wintypes.DWORD,wintypes.BOOL,wintypes.DWORD],wintypes.HANDLE),
            'GetProcessId':([wintypes.HANDLE],wintypes.DWORD),
            'GetProcessIdOfThread':([wintypes.HANDLE],wintypes.DWORD),
            'WaitForSingleObject':([wintypes.HANDLE,wintypes.DWORD],wintypes.DWORD),
            'ResumeThread':([wintypes.HANDLE],wintypes.DWORD),
            'CloseHandle':([wintypes.HANDLE],wintypes.BOOL),
        }
        for name,(args,result) in signatures.items():
            function=getattr(kernel,name);function.argtypes=args;function.restype=result
        execution.remaining()
        process=int(self._handle)
        pid=kernel.GetProcessId(process)
        if pid!=self.pid or kernel.WaitForSingleObject(process,0)!=0x102:
            raise OSError('Owned suspended worker is not live')
        snapshot=kernel.CreateToolhelp32Snapshot(0x4,0)  # TH32CS_SNAPTHREAD
        if snapshot==ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry=ThreadEntry();entry.dwSize=ctypes.sizeof(entry)
            found=[]
            ok=kernel.Thread32First(snapshot,ctypes.byref(entry))
            while ok:
                if entry.th32OwnerProcessID==pid:found.append(entry.th32ThreadID)
                entry.dwSize=ctypes.sizeof(entry)
                ok=kernel.Thread32Next(snapshot,ctypes.byref(entry))
            if ctypes.get_last_error()!=18:  # ERROR_NO_MORE_FILES
                raise ctypes.WinError(ctypes.get_last_error())
            if len(found)!=1:raise OSError('Cannot uniquely identify owned suspended initial thread')
            thread=kernel.OpenThread(0x0002|0x0800,False,found[0])  # SUSPEND_RESUME | QUERY_LIMITED_INFORMATION
            if not thread:raise ctypes.WinError(ctypes.get_last_error())
            try:
                if (kernel.GetProcessIdOfThread(thread)!=pid or
                        kernel.GetProcessId(process)!=pid or
                        kernel.WaitForSingleObject(process,0)!=0x102):
                    raise OSError('Suspended initial thread ownership verification failed')
                # Still under OWNED_LOCK: shutdown cannot miss or race resume.
                execution.remaining()
                if kernel.ResumeThread(thread)!=1:
                    raise OSError('Could not resume owned initial thread exactly once')
            finally:kernel.CloseHandle(thread)
        finally:kernel.CloseHandle(snapshot)

    def _prepare_job(self):
        import ctypes
        from ctypes import wintypes
        class Basic(ctypes.Structure):
            _fields_=[('PerProcessUserTimeLimit',ctypes.c_int64),('PerJobUserTimeLimit',ctypes.c_int64),('LimitFlags',wintypes.DWORD),('MinimumWorkingSetSize',ctypes.c_size_t),('MaximumWorkingSetSize',ctypes.c_size_t),('ActiveProcessLimit',wintypes.DWORD),('Affinity',ctypes.c_size_t),('PriorityClass',wintypes.DWORD),('SchedulingClass',wintypes.DWORD)]
        class Counters(ctypes.Structure):
            _fields_=[(name,ctypes.c_uint64) for name in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
        class Extended(ctypes.Structure):
            _fields_=[('BasicLimitInformation',Basic),('IoInfo',Counters),('ProcessMemoryLimit',ctypes.c_size_t),('JobMemoryLimit',ctypes.c_size_t),('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR];kernel.CreateJobObjectW.restype=wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD];kernel.SetInformationJobObject.restype=wintypes.BOOL
        kernel.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE];kernel.AssignProcessToJobObject.restype=wintypes.BOOL
        kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
        handle=kernel.CreateJobObjectW(None,None)
        if not handle:raise OSError('Could not create owned native worker job')
        self._art_job=(kernel,handle)
        info=Extended();info.BasicLimitInformation.LimitFlags=0x2000
        if not kernel.SetInformationJobObject(handle,9,ctypes.byref(info),ctypes.sizeof(info)):
            kernel.CloseHandle(handle);self._art_job=None
            raise OSError('Could not configure native worker cleanup')

    def close_tree(self):
        with self._art_guard:
            if self._art_tree_closed:return
            self._art_tree_closed=True
            if os.name=='nt':
                if self._art_job is not None:
                    kernel,handle=self._art_job;kernel.CloseHandle(handle);self._art_job=None
            else:
                try:os.killpg(self.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            if self.poll() is None:
                try:super().kill()
                except ProcessLookupError:pass
                self.wait(timeout=5)
            with OWNED_LOCK:OWNED_PROCESSES.discard(self)

    def __exit__(self,*exc):
        self.close_tree()
        return super().__exit__(*exc)
