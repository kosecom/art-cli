"""Synthetic review peer/worker only; no vendor services or user configuration."""
import json
import os
from pathlib import Path
import sys
import time


def main():
    kind, root = sys.argv[1:3]
    root = Path(root)
    if kind.startswith('worker'):
        from art_cli.config import Store
        from art_cli.worker import serve
        def executable(self, app):
            if kind == 'worker-late':
                (root/'ready').write_text('ready')
                time.sleep(.6)
            return Path(sys.executable)
        Store.executable = executable
        return serve(home=root, heartbeat_interval=.1, heartbeat_timeout=.4)
    if kind == 'child':
        (root/'pid').write_text(str(os.getpid()))
        time.sleep(30)
        return 0
    delay = float(sys.argv[3])
    pages = int(sys.argv[4])
    for line in sys.stdin:
        request = json.loads(line)
        method = request.get('method')
        with (root/'requests').open('a', encoding='utf-8') as stream:
            stream.write(method+'\n')
        if 'id' not in request:
            continue
        if method == 'initialize':
            time.sleep(delay)
            result = {'protocolVersion':'2025-11-25','capabilities':{'tools':{}},'serverInfo':{'name':'SYNTHETIC'}}
        elif method == 'tools/list':
            time.sleep(delay)
            page = int(request.get('params',{}).get('cursor',0))
            result = {'tools': []}
            if page+1 < pages:
                result['nextCursor'] = str(page+1)
        else:
            result = {'echo':request.get('params',{})}
        print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
