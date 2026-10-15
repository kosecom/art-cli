"""Optional one-worker MCP/SSH frontend. Native apps remain completely lazy."""
import json
import os
import sys
import threading
import time
import uuid
from .api import dispatch
from .rpc import ACTIVE_LOCK,ACTIVE_SESSIONS,MAX_LINE,canonical,strict_json,valid_id
from .processes import shutdown_owned

OPERATIONS=['catalog','search','describe','execute','batch','doctor','refresh','guide','native','rpc','control']
TOOL={'name':'art','description':'One ArtCraft entry. Start with catalog/guide, then search and describe for exact native schemas. execute/batch start only selected native apps; explicit save/export required. All raw vendor CLI functions through native; resources/prompts through rpc. Not automatic live GUI control.','inputSchema':{'type':'object','properties':{'operation':{'type':'string','enum':OPERATIONS},'arguments':{'type':'object'}},'required':['operation'],'additionalProperties':False}}


def serve(home=None,heartbeat_interval=30,heartbeat_timeout=90):
    lock=threading.RLock();state_lock=threading.RLock();stop=threading.Event()
    active={};pending={};initialized=False;workers=[]
    def send(value):
        data=(canonical(value)+'\n').encode('utf-8')
        if len(data)>MAX_LINE:raise ValueError('Output frame exceeds transport limit')
        with lock:sys.stdout.buffer.write(data);sys.stdout.buffer.flush()
    def error(ident,code,message):send({'jsonrpc':'2.0','id':ident,'error':{'code':code,'message':message}})
    def shutdown():
        stop.set()
        with state_lock:
            for event in active.values():event.set()
        shutdown_owned()  # Fence first: initializing/late jobs cannot escape the snapshot.
        with ACTIVE_LOCK:sessions=list(ACTIVE_SESSIONS)
        for session in sessions:session.close()
        deadline=time.monotonic()+3
        for thread in list(workers):
            if thread is not threading.current_thread():thread.join(timeout=max(0,deadline-time.monotonic()))
    def work(ident,operation,args,event,mcp=False):
        try:
            result=dispatch(operation,args,home=home,cancel_event=event)
            if mcp:
                images=[]
                for step in result.get('steps',[]):
                    for block in step.get('result',{}).get('content',[]):
                        if block.get('type')=='image':images.append(block)
                result={'content':[{'type':'text','text':canonical(result)},*images],'structuredContent':result,'isError':not result.get('ok',False)}
            send({'jsonrpc':'2.0','id':ident,'result':result})
        except (OSError,ValueError):
            try:error(ident,-32603,'Worker output/transport error; completion uncertain')
            except (OSError,ValueError):shutdown()
        finally:
            with state_lock:active.pop(ident,None)
    def heartbeat():
        while not stop.wait(heartbeat_interval):
            if not initialized:continue
            with state_lock:
                expired=any(time.monotonic()-t>heartbeat_timeout for t in pending.values())
                ident='art-ping-'+uuid.uuid4().hex
                if not expired:pending[ident]=time.monotonic()
            if expired:
                shutdown()
                os._exit(3)  # dedicated worker only; all owned children closed first
            try:send({'jsonrpc':'2.0','id':ident,'method':'ping'})
            except OSError:shutdown();os._exit(3)
    threading.Thread(target=heartbeat,daemon=True).start()
    try:
        while not stop.is_set():
            line=sys.stdin.buffer.readline(MAX_LINE+1)
            if not line:break
            if len(line)>MAX_LINE or not line.endswith(b'\n'):break
            try:message=strict_json(line.decode('utf-8'))
            except (ValueError,UnicodeError):error(None,-32700,'Invalid JSON frame');continue
            if not isinstance(message,dict) or message.get('jsonrpc')!='2.0':error(None,-32600,'Invalid JSON-RPC');continue
            ident=message.get('id');method=message.get('method');params=message.get('params',{})
            if method is None:
                # Responses may be malformed or unsolicited: never index with
                # containers, booleans or floats (which can alias integer IDs).
                if not valid_id(ident):continue
                with state_lock:pending.pop(ident,None)
                continue
            if not isinstance(params,dict):error(ident,-32602,'params must be an object');continue
            if method=='notifications/cancelled':
                request_id=params.get('requestId')
                # Invalid notifications receive no reply and cannot cancel a
                # different request through Python's bool/int key equality.
                if not valid_id(request_id):continue
                with state_lock:event=active.get(request_id)
                if event:event.set()
                continue
            if ident is None:continue
            if not valid_id(ident):error(None,-32600,'Invalid request id');continue
            if method=='initialize':
                if initialized:error(ident,-32600,'Already initialized');continue
                initialized=True
                send({'jsonrpc':'2.0','id':ident,'result':{'protocolVersion':'2025-11-25','capabilities':{'tools':{}},'serverInfo':{'name':'art-cli','version':'0.2.0'}}})
            elif method=='ping':send({'jsonrpc':'2.0','id':ident,'result':{}})
            elif not initialized:error(ident,-32002,'Initialize first')
            elif method=='tools/list':send({'jsonrpc':'2.0','id':ident,'result':{'tools':[TOOL]}})
            elif method in ('art/dispatch','tools/call'):
                if method=='tools/call':
                    if params.get('name')!='art':error(ident,-32602,'Unknown tool');continue
                    params=params.get('arguments',{})
                if not isinstance(params,dict) or params.get('operation') not in OPERATIONS or not isinstance(params.get('arguments',{}),dict):error(ident,-32602,'Invalid ART operation');continue
                with state_lock:
                    if stop.is_set():break
                    if active:error(ident,-32016,'Worker busy; no operation dispatched');continue
                    event=threading.Event();active[ident]=event
                    workers[:]=[t for t in workers if t.is_alive()]
                    thread=threading.Thread(target=work,args=(ident,params['operation'],params.get('arguments',{}),event,method=='tools/call'),daemon=True)
                    workers.append(thread)
                    thread.start()
            else:error(ident,-32601,'Method not supported')
    finally:shutdown()
    return 0
