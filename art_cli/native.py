"""Bounded original CLI invocation with optional stdin, owned cleanup and no replay."""
import subprocess
import threading
import time
from .processes import OwnedPopen,current_execution
from .rpc import RpcError

MAX_BYTES=64*1024*1024


def run(command,*,input_text=None,timeout=120,cancel_event=None):
    execution=current_execution(timeout,cancel_event)
    execution.remaining()
    if input_text is not None and not isinstance(input_text,str):raise ValueError('native stdin must be text')
    data=input_text.encode('utf-8') if input_text is not None else None
    if data is not None and len(data)>MAX_BYTES:raise ValueError('Native stdin exceeds size limit')
    process=OwnedPopen(command,execution=execution,stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,shell=False)
    output={'stdout':bytearray(),'stderr':bytearray()};lock=threading.Lock();over=threading.Event();errors=[]
    threads=[]
    def read(name,stream):
        try:
            while True:
                chunk=stream.read(65536)
                if not chunk:return
                with lock:
                    if len(output['stdout'])+len(output['stderr'])+len(chunk)>MAX_BYTES:
                        over.set();process.close_tree();return
                    output[name].extend(chunk)
        except (OSError,ValueError):
            with lock:errors.append('reader')
    def write():
        try:process.stdin.write(data);process.stdin.flush()
        except (OSError,ValueError):pass
        finally:
            try:process.stdin.close()
            except (OSError,ValueError):pass
    try:
        for name in ('stdout','stderr'):
            thread=threading.Thread(target=read,args=(name,getattr(process,name)),daemon=True);thread.start();threads.append(thread)
        if data is not None:
            writer=threading.Thread(target=write,daemon=True);writer.start();threads.append(writer)
        deadline=execution.deadline
        while process.poll() is None:
            execution.remaining()
            if cancel_event is not None and cancel_event.is_set():raise RpcError(-32800,'Native CLI cancelled; completion uncertain; no retry')
            if over.is_set():raise RpcError(-32017,'Native output limit exceeded; completion uncertain; inspect output files')
            if time.monotonic()>=deadline:raise RpcError(-32012,'Native CLI timed out; completion uncertain; no retry')
            time.sleep(.02)
        for thread in threads:
            while thread.is_alive():thread.join(timeout=min(.05,execution.remaining()))
        execution.remaining()
        if over.is_set():raise RpcError(-32017,'Native output limit exceeded; completion uncertain; inspect output files')
        if errors or any(t.is_alive() for t in threads):raise RpcError(-32012,'Native CLI output did not complete within deadline; completion uncertain')
        return {'exit_code':process.returncode,'stdout':output['stdout'].decode('utf-8','replace'),'stderr':output['stderr'].decode('utf-8','replace')}
    finally:
        process.close_tree()
        for thread in threads:thread.join(timeout=2)
        for stream in (process.stdin,process.stdout,process.stderr):
            if stream is not None:
                try:stream.close()
                except (OSError,ValueError):pass
