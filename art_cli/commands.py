"""Second disclosure layer: every native editor command, without eager tool flooding."""
from datetime import datetime,timezone
import os
import subprocess
from .bindings import payload
from .config import atomic_json,require_app
from .rpc import Session,strict_json
from .processes import current_execution

EXECUTORS={'cadcraft':('execute','command'),'deckcraft':('run_command','command'),'designcraft':('execute','command'),'effectcraft':('command_run','id'),'figcraft':('run_command','command'),'filmcraft':('command_run','id'),'gridcraft':('execute_command','command'),'lightcraft':('command_run','id'),'pdfcraft':('command_run','id'),'photocraft':('command_run','id'),'soundcraft':('execute','command'),'vectorcraft':('command_run','id'),'wordcraft':('execute','command')}


def cache_path(store,app,mode):
    p=store.cache_path(app,mode)
    return p.with_name(p.stem+'-commands.json')


def cached_commands(store,app,mode='headless'):
    path=cache_path(store,app,mode)
    if not path.is_file():return None
    try:
        data=strict_json(path.read_text(encoding='utf-8'))
        if not isinstance(data,dict):return None
        stored=data.get('identity',{})
        if not isinstance(stored,dict) or 'command' in stored:return None
        ident=store.identity(app,mode,digest=True)
        if ident is None or any(stored.get(k)!=v for k,v in ident.items()):return None
        return data
    except (ValueError,OSError,KeyError,TypeError):return None


def command_catalog(store,app,mode='headless',timeout=120,force=False):
    execution=current_execution(timeout)
    execution.remaining()
    require_app(app)
    previous=None if force else cached_commands(store,app,mode)
    execution.remaining()
    if previous is not None:return previous
    source='native_mcp_registry'
    if app=='figcraft':
        # Its MCP registry is human text; the official native CLI returns exact JSON.
        # The generic UI control path remains available for live dynamic UI menus.
        exe=store.executable(app)
        if exe is None:raise FileNotFoundError('figcraft CLI not installed')
        from .native import run
        proc=run([str(exe),'commands','--json'],timeout=timeout)
        if proc['exit_code']:raise ValueError('FigCraft native command discovery failed')
        commands=strict_json(proc['stdout']);source='native_cli_registry_headless'
    else:
        with Session(app,store.command(app,mode),timeout) as session:
            tools=session.collect('tools/list','tools')
            name=next((n for n in ('command_list','list_commands') if any(t['name']==n for t in tools)),None)
            if name is None:raise ValueError('No command registry advertised by native app')
            params={'schemas':True} if app=='effectcraft' else {}
            result=session.rpc('tools/call',{'name':name,'arguments':params})
            if result.get('isError'):raise ValueError('Native command registry returned isError')
            commands=payload(result)
            if isinstance(commands,dict):commands=commands.get('commands')
    if not isinstance(commands,list) or not all(isinstance(c,dict) and isinstance(c.get('id'),str) for c in commands):raise ValueError('Invalid native command registry payload')
    unique_ids=len({c['id'] for c in commands})
    data={'app':app,'mode':mode,'source':source,'identity':store.identity(app,mode,digest=True),'captured_at':datetime.now(timezone.utc).isoformat(),'commands':commands,'count':len(commands),'unique_ids':unique_ids,'duplicate_entries':len(commands)-unique_ids,'note':'Native duplicate ID variants are preserved. Enabled/disabled flags are discovery snapshots, not authorization or current document state. UI-only actions require configured control/attach.'}
    execution.remaining()
    atomic_json(cache_path(store,app,mode),data)
    execution.remaining()
    return data


def invocation(app,entry,params=None):
    if app=='pdfcraft':
        mapped=entry.get('tool')
        if not mapped:return {'app':app,'command':entry['id'],'execution':'requires_gui_or_other_native_api','note':'No upstream headless command mapping. Use native full tools or configured GUI control; do not infer a mapping from the ID.'}
        return {'app':app,'tool':mapped,'arguments':params or {}}
    tool,key=EXECUTORS[app]
    return {'app':app,'tool':tool,'arguments':{key:entry['id'],'params':params or {}}}
