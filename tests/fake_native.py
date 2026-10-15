"""Explicitly synthetic stdio peer used only by tests."""
import json,sys,time,os
TOOLS=[{'name':name,'inputSchema':{'type':'object','properties':{'value':{}},'additionalProperties':False}} for name in ('echo','fail','rpcfail','slow','callback','image')]
def send(x):print(json.dumps(x),flush=True)
for line in sys.stdin:
    m=json.loads(line);method=m.get('method');ident=m.get('id')
    if ident is None:continue
    if method=='initialize':result={'protocolVersion':'2025-11-25','capabilities':{'tools':{}},'serverInfo':{'name':'SYNTHETIC','version':'test'}}
    elif method=='tools/list':result={'tools':TOOLS}
    elif method=='ping':result={}
    elif method=='tools/call':
        name=m['params']['name'];args=m['params'].get('arguments',{})
        if name=='slow':time.sleep(10)
        if name=='rpcfail':send({'jsonrpc':'2.0','id':ident,'error':{'code':-32042,'message':'synthetic exact error','data':{'source':'fixture'}}});continue
        if name=='callback':
            send({'jsonrpc':'2.0','id':'permission-test','method':'elicitation/create','params':{'message':'SYNTHETIC approval'}})
            reply=json.loads(sys.stdin.readline());result={'content':[{'type':'text','text':json.dumps(reply)}]}
        elif name=='image':result={'content':[{'type':'image','mimeType':'image/png','data':'SYNTHETIC_NOT_A_REAL_IMAGE'}],'structuredContent':{'fixture':True}}
        else:result={'content':[{'type':'text','text':json.dumps({'value':args.get('value'),'pid':os.getpid()})}],'isError':name=='fail'}
    else:send({'jsonrpc':'2.0','id':ident,'error':{'code':-32601,'message':'test method not found'}});continue
    send({'jsonrpc':'2.0','id':ident,'result':result})
