"""Unified CLI; model/native arguments never pass through a shell."""
import argparse
import json
from pathlib import Path
import sys
from .api import dispatch
from .rpc import strict_json


def main(argv=None):
    # JSON is a UTF-8 wire format even when Windows redirects a legacy-codepage
    # console. Do not depend on the agent's PYTHONUTF8 environment settings.
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(prog='art',description='ART-CLI: one on-demand ArtCraft Hermes plugin for Windows and macOS.')
    p.add_argument('--home',help='Owning Hermes profile home (data stored under art-cli/)')
    p.add_argument('--platform',choices=['windows','mac','local'],help='Exact native target, or explicitly configured route')
    p.add_argument('--timeout',type=float,default=120,help='Total execution timeout in seconds (1..3600)')
    p.add_argument('--mode',default='headless',help='Isolated headless, or operator-configured native GUI mode')
    p.add_argument('--output',help='Also write complete JSON result to this file')
    commands=p.add_subparsers(dest='operation',required=True)
    for name in ('catalog','doctor','refresh'):
        cmd=commands.add_parser(name)
        cmd.add_argument('--app',help='Exact app identifier; omit to list all apps')
    search=commands.add_parser('search');search.add_argument('query',nargs='?',default='');search.add_argument('--app');search.add_argument('--offset',type=int,default=0);search.add_argument('--limit',type=int,default=50);search.add_argument('--scope',choices=['all','tools','commands'],default='all')
    describe=commands.add_parser('describe');describe.add_argument('app');describe.add_argument('tool');describe.add_argument('--kind',choices=['tool','command'],default='tool')
    call=commands.add_parser('call');call.add_argument('app');call.add_argument('tool');call.add_argument('--schema-hash')
    group=call.add_mutually_exclusive_group();group.add_argument('--args',default=None);group.add_argument('--args-file')
    batch=commands.add_parser('batch');batch.add_argument('--file',required=True,help='JSON array of ordered app/tool/arguments steps')
    native=commands.add_parser('native');native.add_argument('--stdin-file');native.add_argument('app');native.add_argument('argv',nargs=argparse.REMAINDER)
    rpc=commands.add_parser('rpc');rpc.add_argument('app');rpc.add_argument('method');rpc.add_argument('--params',default='{}')
    control=commands.add_parser('control');control.add_argument('app');control.add_argument('method');control.add_argument('--params',default='{}');control.add_argument('--control-name')
    guide=commands.add_parser('guide');guide.add_argument('--app')
    commands.add_parser('worker');commands.add_parser('mcp')
    args=vars(p.parse_args(argv));operation=args.pop('operation');home=args.pop('home');output=args.pop('output')
    if operation in ('worker','mcp'):
        from .worker import serve
        return serve(home=home)
    try:
        if operation=='call':
            operation='execute'
            file=args.pop('args_file');raw=args.pop('args')
            args['arguments']=strict_json(Path(file).read_text(encoding='utf-8')) if file else strict_json(raw or '{}')
        elif operation=='batch':
            args['steps']=strict_json(Path(args.pop('file')).read_text(encoding='utf-8'))
        elif operation in ('rpc','control'):args['params']=strict_json(args['params'])
        elif operation=='native':
            file=args.pop('stdin_file')
            if file:args['stdin']=Path(file).read_text(encoding='utf-8')
            if args['argv'] and args['argv'][0]=='--':args['argv']=args['argv'][1:]
        result=dispatch(operation,{k:v for k,v in args.items() if v is not None},home=home)
        text=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
        if output:Path(output).write_text(text,encoding='utf-8')
        print(text,end='')
        return 0 if result.get('ok') else 1
    except (OSError,ValueError) as exc:
        print(json.dumps({'ok':False,'error':{'code':'input_or_output','message':str(exc)}}))
        return 2

if __name__=='__main__':raise SystemExit(main())
