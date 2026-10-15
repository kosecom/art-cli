#!/usr/bin/env python3
"""Download a pinned official ArtCraft CLI into a NEW staging directory only.
No app install, PATH/route/config selection, authentication bypass or service changes.
"""
import argparse,json
from pathlib import Path
from art_cli.config import APPS
from art_cli.dependencies import stage

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',choices=list(APPS),required=True)
    parser.add_argument('--version',required=True)
    parser.add_argument('--target',type=Path,required=True)
    args=parser.parse_args()
    try:print(json.dumps(stage(args.app,args.version,args.target),indent=2));return 0
    except (OSError,ValueError,KeyError) as exc:print(json.dumps({'ok':False,'error':str(exc)}));return 1
if __name__=='__main__':raise SystemExit(main())
