"""One on-demand engine shared by the Hermes plugin, CLI and MCP adapter."""
from __future__ import annotations
from contextlib import ExitStack
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import subprocess
import threading
import time
from .config import APPS,Store,native_platform,require_app
from .rpc import Session,RpcError,fingerprint
from .bindings import reference,preflight,resolve
from .commands import command_catalog,cached_commands,invocation
from .processes import CURRENT_EXECUTION,current_execution

STATE_WARNING='State exists only in this job. Include native save/export before the job ends. Failure may follow partial side effects; never retry a mutation blindly.'
GUIDE='''ART-CLI — one ArtCraft integration for Hermes, Windows and macOS.

1. Install the official ArtCraft apps and their matching native standalone CLIs.
   Windows: standard Program Files directories are discovered automatically.
   macOS: app bundle CLIs or ~/.local/share/artcraft/cli are discovered; a GUI
   installation alone may NOT contain the CLI. Never disable Gatekeeper.
2. Install this package using the supplied installer / Hermes plugins install.
   Profile settings and caches live in <Hermes home>/art-cli. User-specific
   executable and remote route overrides are operator configuration, not tools.
3. art catalog: installed apps and cached metadata; no native process starts.
   art refresh --app figcraft: query just that app, then close it.
   art search export --app figcraft: small matching function summaries.
   art describe figcraft run_command: exact native JSON input schema.
   art search frame --app figcraft --scope commands: nested editor functions.
   art describe figcraft node.create --kind command: native parameters/dispatch.
4. art call APP TOOL --args-file arguments.json: one isolated job.
   art batch --file job.json: ordered [{app,tool,arguments}] steps sharing state.
   Create/edit/save/export belong in ONE batch. No implicit autosave or rollback.
   Use native list_commands/command_list then describe_command/command_info to
   disclose editor commands behind execute_command/command_run dispatchers.
5. art native APP -- <vendor arguments>: every vendor CLI command without shell
   interpolation. Secrets do not belong in argv. Use the vendor protected input.
   art native --stdin-file job.jsonl APP -- serve: original stdin CLI protocols.
   art rpc APP resources/list --params '{}': supported native MCP resources,
   prompts and completions, preserving result types and native errors.
   art control APP METHOD --params '{}': operator-bound native live GUI control.
   Hermes art_rpc uses arguments.transport=control for the same complete path.
6. art doctor: binary/config/cache state, not a claim that a GUI action worked.
   Updated binaries invalidate metadata; execution always reads current schemas.
   A described schema_hash can be supplied to execute to refuse schema drift.
7. --platform windows/mac selects that exact native target. Remote use requires
   an explicit trusted command in config.json launching art worker on the host.
   No automatic SSH trust, credentials, gateway restart, or customer-host access.
8. Headless is the default. GUI requires an operator-configured native bridge
   mode for that app, local authenticated endpoint and the user's own GUI state.
   No default headless call changes a currently open GUI document. UI/hardware
   only functions not exposed by upstream cannot be invented by this wrapper.
9. App processes start only for actual discovery/work and close after the job.
   The plugin remains registered with compact tools, not hundreds of eager
   definitions. Unsupported approval callbacks fail; approval is never forged.

CLI: python -m art_cli --help. Install/uninstall: python install.py --help.
No app code/assets are bundled. Native ArtCraft and third-party licenses apply.
'''


def _timeout(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 1<=value<=3600:raise ValueError('timeout must be between 1 and 3600 seconds')
    return float(value)


def _validate(schema,value,path='arguments'):
    """Fast structural preflight; authoritative validation is the native server."""
    if reference(value):return
    if not isinstance(schema,dict):return
    if 'enum' in schema and value not in schema['enum']:raise ValueError(path+' not in enum')
    if 'const' in schema and value!=schema['const']:raise ValueError(path+' differs from const')
    types=schema.get('type');types=[types] if isinstance(types,str) else types
    checks={'object':lambda:isinstance(value,dict),'array':lambda:isinstance(value,list),'string':lambda:isinstance(value,str),'boolean':lambda:isinstance(value,bool),'integer':lambda:isinstance(value,int) and not isinstance(value,bool),'number':lambda:isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value),'null':lambda:value is None}
    if types and not any(checks.get(t,lambda:True)() for t in types):raise ValueError(path+' has the wrong type')
    if isinstance(value,dict):
        for name in schema.get('required',[]):
            if name not in value:raise ValueError(path+'.'+name+' is required')
        props=schema.get('properties',{})
        for name,item in value.items():
            if name not in props and schema.get('additionalProperties') is False:raise ValueError(path+'.'+name+' is not allowed')
            _validate(props.get(name,{}),item,path+'.'+name)
    if isinstance(value,list):
        if len(value)<schema.get('minItems',0) or len(value)>schema.get('maxItems',len(value)):raise ValueError(path+' array length outside schema')
        for index,item in enumerate(value):_validate(schema.get('items',{}),item,f'{path}[{index}]')
    if isinstance(value,(float,int)) and not isinstance(value,bool):
        if not math.isfinite(value):raise ValueError(path+' must be finite')
        if 'minimum' in schema and value<schema['minimum']:raise ValueError(path+' below minimum')
        if 'maximum' in schema and value>schema['maximum']:raise ValueError(path+' above maximum')


def _capture(store,app,mode,session):
    tools=session.collect('tools/list','tools')
    names=set()
    for item in tools:
        if not isinstance(item,dict) or not isinstance(item.get('name'),str) or not isinstance(item.get('inputSchema'),dict) or item['name'] in names:raise ValueError('Invalid/duplicate native tool schema')
        names.add(item['name'])
    value={'app':app,'platform':native_platform(),'mode':mode,'captured_at':datetime.now(timezone.utc).isoformat(),'identity':store.identity(app,mode,digest=True),'serverInfo':session.info.get('serverInfo',{}),'protocolVersion':session.info.get('protocolVersion'),'capabilities':session.info.get('capabilities',{}),'tools':tools,'schema_hash':fingerprint(tools)}
    current_execution().remaining()
    store.save(app,value,mode)
    current_execution().remaining()
    return value


def _metadata(store,app,mode,timeout,force=False):
    current_execution(timeout).remaining()
    require_app(app)
    cached=None if force else store.cached(app,mode)
    current_execution(timeout).remaining()
    if cached:return cached
    with Session(app,store.command(app,mode),timeout) as session:return _capture(store,app,mode,session)


def _catalog(store,mode):
    apps=[]
    for app,name in APPS.items():
        current_execution().remaining()
        exe=store.executable(app)
        data=store.cached(app,mode) if exe else None
        commands=cached_commands(store,app,mode) if exe else None
        apps.append({'app':app,'name':name,'installed':exe is not None,'executable':str(exe) if exe else None,'metadata':'cached' if data else 'not_cached_or_changed','tool_count':len(data['tools']) if data else None,'command_count':commands['count'] if commands else None,'modes':['headless',*store.config.get('apps',{}).get(app,{}).get('modes',{})]})
    current_execution().remaining()
    return {'ok':True,'platform':native_platform(),'apps':apps,'count':len(apps),'worker_started':False}


def _steps(arguments):
    steps=arguments.get('steps')
    if not isinstance(steps,list) or not 1<=len(steps)<=256:raise ValueError('batch requires 1..256 steps')
    for index,step in enumerate(steps):
        if not isinstance(step,dict) or set(step)-{'app','tool','arguments','mode','schema_hash'}:raise ValueError('Invalid batch step fields')
        require_app(step.get('app'))
        if not isinstance(step.get('tool'),str) or not step['tool']:raise ValueError('Exact native tool name required')
        if not isinstance(step.get('arguments',{}),dict):raise ValueError('Native tool arguments must be an object')
        preflight(step.get('arguments',{}),index)
    return steps


def _batch(store,arguments,timeout,cancel_event=None):
    try:
        steps=_steps(arguments)
    except (ValueError,TypeError) as exc:
        return {'ok':False,'platform':native_platform(),'state_scope':'job','steps':[],'completion':'not_dispatched','error':{'code':'preflight','message':str(exc)}}
    default_mode=arguments.get('mode','headless')
    execution=current_execution(timeout,cancel_event)
    result={'ok':False,'platform':native_platform(),'state_scope':'job','warning':STATE_WARNING,'steps':[],'completion':'not_started'}
    sessions={};metadata={}
    def remaining():
        return execution.remaining()
    with ExitStack() as stack:
        try:
            # Discover and preflight the complete batch before invoking any tool.
            for step in steps:
                app=step['app'];mode=step.get('mode',default_mode);key=(app,mode)
                if key not in sessions:
                    command=store.command(app,mode)
                    session=stack.enter_context(Session(app,command,remaining()))
                    sessions[key]=session
                    metadata[key]=_capture(store,app,mode,session)
                entry=metadata[key]
                if step.get('schema_hash') and step['schema_hash']!=entry['schema_hash']:raise RpcError(-32014,'Native schema changed; describe again before executing',{'app':app,'schema_hash':entry['schema_hash']})
                schema=next((s for s in entry['tools'] if s['name']==step['tool']),None)
                if schema is None:raise ValueError(app+': unknown native tool '+step['tool'])
                _validate(schema['inputSchema'],step.get('arguments',{}))
            result['completion']='in_progress'
            for step in steps:
                session=sessions[(step['app'],step.get('mode',default_mode))];session.timeout=remaining()
                actual_args=resolve(step.get('arguments',{}),result['steps'])
                actual_schema=next(s for s in metadata[(step['app'],step.get('mode',default_mode))]['tools'] if s['name']==step['tool'])
                _validate(actual_schema['inputSchema'],actual_args)
                native=session.rpc('tools/call',{'name':step['tool'],'arguments':actual_args})
                result['steps'].append({'app':step['app'],'tool':step['tool'],'result':native})
                if isinstance(native,dict) and native.get('isError'):
                    result['completion']='native_error';return result
            result.update(ok=True,completion='completed')
        except RpcError as exc:
            result['error']=exc.error
            result['completion']='uncertain' if result['completion']=='in_progress' else 'not_dispatched'
        except (ValueError,OSError) as exc:
            result['error']={'code':'preflight_or_io','message':str(exc)}
            result['completion']='uncertain' if result['completion']=='in_progress' else 'not_dispatched'
    return result


def dispatch(operation,arguments=None,*,home=None,cancel_event=None):
    """Bind one budget, including nested guide/native and every discovery phase."""
    token=None
    try:
        args={} if arguments is None else arguments
        if not isinstance(args,dict):raise ValueError('arguments must be an object')
        execution=current_execution(_timeout(args.get('timeout',120)),cancel_event)
        token=CURRENT_EXECUTION.set(execution)
        execution.remaining()
        return _dispatch(operation,args,home=home,cancel_event=cancel_event)
    except RpcError as exc:
        return {'ok':False,'platform':native_platform(),'error':exc.error,'completion':'uncertain'}
    except (ValueError,TypeError) as exc:
        return {'ok':False,'platform':native_platform(),'error':{'code':'configuration_or_input','message':str(exc)}}
    finally:
        if token is not None:CURRENT_EXECUTION.reset(token)


def _dispatch(operation,arguments=None,*,home=None,cancel_event=None):
    """No exception hides a partial native write; never auto-retry a failed job."""
    try:
        args={} if arguments is None else arguments
        if not isinstance(args,dict):raise ValueError('arguments must be an object')
        if operation=='guide' and not args.get('app'):return {'ok':True,'guide':GUIDE,'worker_started':False}
        store=Store(home);mode=args.get('mode','headless');timeout=current_execution().remaining()
        route=store.route(args.get('platform'))
        if route:
            forwarded=dict(args);forwarded.pop('platform',None)
            with Session('art-remote',route['command'],timeout) as peer:
                response=peer.rpc('art/dispatch',{'operation':operation,'arguments':forwarded})
            expected=route.get('platform',args['platform'])
            if not isinstance(response,dict) or response.get('platform')!=expected:raise ValueError('Remote target platform did not match route; result not accepted')
            return response
        if native_platform()=='unsupported':raise ValueError('Native execution supports Windows/macOS; configure a trusted remote route')
        if operation=='guide':
            app=require_app(args.get('app'))
            from .control import profiles
            help_result=dispatch('native',{'app':app,'argv':['help' if app=='filmcraft' else '--help'],'timeout':args.get('timeout',120)},home=home,cancel_event=cancel_event)
            return {'ok':help_result['ok'],'platform':native_platform(),'app':app,'guide':GUIDE,'native_help':help_result.get('stdout','')+help_result.get('stderr',''),'control_profile':profiles()[app],'error':help_result.get('error')}
        if operation=='control' or (operation=='rpc' and args.get('transport')=='control'):
            from .control import call_control
            if set(args)-{'app','method','params','control_name','platform','transport','timeout','mode'}:raise ValueError('Unsupported control call fields')
            control_args={k:args[k] for k in ('app','method','params','control_name','platform') if k in args}
            return {'platform':native_platform(),**call_control(store,control_args,current_execution().remaining())}
        if operation in ('catalog','doctor'):
            if args.get('app'):
                app=require_app(args['app']);entry=store.cached(app,mode)
                current_execution().remaining()
                if entry:return {'ok':True,**entry,'count':len(entry['tools']),'worker_started':False}
                return {'ok':True,'platform':native_platform(),'app':app,'metadata':'not_cached_or_changed','count':0,'worker_started':False}
            return _catalog(store,mode)
        if operation=='refresh':
            apps=[require_app(args['app'])] if args.get('app') else list(APPS)
            rows=[]
            for app in apps:
                try:
                    entry=_metadata(store,app,mode,timeout,force=True)
                    commands=command_catalog(store,app,mode,timeout,force=True) if args.get('commands',True) else None
                    rows.append({'app':app,'ok':True,'tool_count':len(entry['tools']),'command_count':commands['count'] if commands else None,'unique_command_ids':commands['unique_ids'] if commands else None,'schema_hash':entry['schema_hash'],'serverInfo':entry['serverInfo']})
                except (RpcError,ValueError,OSError) as exc:
                    rows.append({'app':app,'ok':False,'error':exc.error if isinstance(exc,RpcError) else str(exc)})
                    if isinstance(exc,RpcError) and exc.error.get('code') in (-32800,-32012):break
            return {'ok':bool(rows) and all(r['ok'] for r in rows),'platform':native_platform(),'apps':rows,'count':len(rows)}
        if operation in ('describe','search'):
            if operation=='describe':require_app(args.get('app'))
            apps=[require_app(args['app'])] if args.get('app') else list(APPS)
            rows=[];not_cached=[];query=str(args.get('query','')).casefold()
            scope=args.get('scope','all')
            if scope not in ('all','tools','commands'):raise ValueError('scope must be all, tools, or commands')
            command_name=args.get('command') or (args.get('tool') if args.get('kind')=='command' else None)
            for app in apps:
                current_execution().remaining()
                entry=_metadata(store,app,mode,timeout) if args.get('app') else store.cached(app,mode)
                if entry is None:not_cached.append(app);continue
                for tool in entry['tools'] if scope!='commands' and not command_name else []:
                    if operation=='describe':
                        if tool['name']==args.get('tool'):return {'ok':True,'platform':native_platform(),'app':app,'tool':tool,'schema_hash':entry['schema_hash']}
                    elif query in (tool['name']+' '+tool.get('description','')).casefold():
                        rows.append({'app':app,'kind':'tool','tool':tool['name'],'description':tool.get('description','')[:500]})
                if scope!='tools' and (operation=='search' or command_name):
                    commands=command_catalog(store,app,mode,timeout) if args.get('app') else cached_commands(store,app,mode)
                    if commands is None:
                        not_cached.append(app+':commands');continue
                    for command in commands['commands']:
                        if operation=='describe' and command['id']==command_name:
                            return {'ok':True,'platform':native_platform(),'app':app,'kind':'command','command':command,'variants':[c for c in commands['commands'] if c['id']==command_name],'invoke':invocation(app,command),'registry_note':commands['note']}
                        if operation=='search' and query in (command['id']+' '+str(command.get('label',''))+' '+str(command.get('menu',''))+' '+str(command.get('params',''))).casefold():
                            rows.append({'app':app,'kind':'command','command':command['id'],'description':str(command.get('label','')),'requires_gui_or_other_api':app=='pdfcraft' and not command.get('tool')})
            if operation=='describe':raise ValueError('Native tool not found; use catalog/search')
            offset=args.get('offset',0);limit=args.get('limit',50)
            if not isinstance(offset,int) or offset<0 or not isinstance(limit,int) or not 1<=limit<=500:raise ValueError('search offset/limit out of range')
            return {'ok':True,'platform':native_platform(),'matches':rows[offset:offset+limit],'total':len(rows),'offset':offset,'has_more':offset+limit<len(rows),'not_cached':not_cached}
        if operation=='execute':
            if args.get('command'):
                if args.get('tool'):raise ValueError('Choose command OR tool, not both')
                app=require_app(args.get('app'));catalog=command_catalog(store,app,mode,timeout)
                entry=next((c for c in catalog['commands'] if c['id']==args['command']),None)
                if entry is None:raise ValueError('Native command not found; search/describe first')
                step=invocation(app,entry,args.get('params',{}))
                if 'tool' not in step:raise ValueError('This command has no upstream headless mapping. Use full native tools or configured GUI control.')
                return _batch(store,{**args,'steps':[step]},timeout,cancel_event)
            step={k:args[k] for k in ('app','tool','arguments','mode','schema_hash') if k in args}
            return _batch(store,{**args,'steps':[step]},timeout,cancel_event)
        if operation=='batch':return _batch(store,args,timeout,cancel_event)
        if operation=='rpc':
            app=require_app(args.get('app'));method=args.get('method')
            allowed={'tools/list','resources/list','resources/templates/list','resources/read','prompts/list','prompts/get','completion/complete','logging/setLevel','ping'}
            if method not in allowed:raise ValueError('Use execute/batch for tools; rpc supports MCP resources/prompts/completion/list/ping only')
            with Session(app,store.command(app,mode),timeout) as session:
                value=session.rpc(method,args.get('params',{}))
            return {'ok':True,'platform':native_platform(),'app':app,'method':method,'result':value}
        if operation=='native':
            app=require_app(args.get('app'));argv=args.get('argv')
            if not isinstance(argv,list) or not argv or not all(isinstance(s,str) and '\x00' not in s for s in argv):raise ValueError('native requires a nonempty JSON argv array')
            exe=store.executable(app)
            if exe is None:raise FileNotFoundError(app+' CLI not installed')
            from .native import run
            result=run([str(exe),*argv],input_text=args.get('stdin'),timeout=timeout,cancel_event=cancel_event)
            return {'ok':result['exit_code']==0,'platform':native_platform(),'app':app,**result,'state_scope':'job','warning':STATE_WARNING}
        raise ValueError('Unknown ART-CLI operation')
    except subprocess.TimeoutExpired:return {'ok':False,'platform':native_platform(),'error':{'code':'timeout','message':'Native command discovery timed out; no automatic retry'},'completion':'uncertain'}
    except RpcError as exc:return {'ok':False,'platform':native_platform(),'error':exc.error,'completion':'uncertain'}
    except (OSError,ValueError,TypeError,KeyError) as exc:return {'ok':False,'platform':native_platform(),'error':{'code':'configuration_or_input','message':str(exc)}}
