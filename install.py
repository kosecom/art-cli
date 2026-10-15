#!/usr/bin/env python3
"""Safe drop-in installer for ART-CLI. Does not alter Hermes core or app installs."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import sys
import tempfile

NAME='art-cli'
MARKER='.art-cli-install.json'
ROOT_FILES=('plugin.yaml','__init__.py','art.py','install.py','setup_art.py','bootstrap.py','README.md','README.de.md','START-HERE.md','SECURITY.md','CONTRIBUTING.md','CHANGELOG.md','LICENSE','NOTICE.md','pyproject.toml','BUILD-MANIFEST.json')

def sha(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()

def safe_path(path):
    """Reject symlinks and Windows reparse points before resolving any path."""
    path=Path(path).absolute()
    for part in (*reversed(path.parents),path):
        try:info=part.lstat()
        except FileNotFoundError:continue
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0) & getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400):
            raise ValueError('Refusing symlink or junction in managed path')
    return path


def managed_paths(home):
    home=safe_path(home)
    for relative in ('plugins/art-cli','plugins/art-cli/'+MARKER,'bin','bin/'+('art.cmd' if os.name=='nt' else 'art'),'art-cli/backups'):
        safe_path(home/relative)
    return home


def package_files(source):
    source=safe_path(source)
    paths=[]
    for name in ROOT_FILES:
        path=safe_path(source/name)
        if path.is_file():paths.append(path)
    folder=safe_path(source/'art_cli')
    if folder.exists():
        for root,dirs,files in os.walk(folder,followlinks=False):
            dirs[:]=[name for name in dirs if name!='__pycache__']
            for name in dirs:safe_path(Path(root)/name)
            for name in files:
                path=Path(root)/name
                if path.suffix in ('.py','.json'):
                    safe_path(path)
                    if path.is_file():paths.append(path)
    for name in ('control.md','ACCEPTANCE.md','ARCHITECTURE.md','SETUP.md','CLI.md','release-verification.json'):
        path=safe_path(source/'docs'/name)
        if path.is_file():paths.append(path)
    for name in ('README.md','banner.png','banner.svg','workflow.png','workflow.svg','capabilities.png','capabilities.svg'):
        path=safe_path(source/'docs/assets'/name)
        if path.is_file():paths.append(path)
    if not all((source/name).is_file() for name in ('plugin.yaml','__init__.py','art.py','art_cli/api.py')):raise ValueError('Source is not a complete ART-CLI package')
    return sorted(set(paths))

def install(source,home,upgrade=False):
    source=safe_path(source);home=managed_paths(home);parent=home/'plugins';target=parent/NAME
    if source==target or target in source.parents or source in target.parents:raise ValueError('Source and installation must be separate directories')
    files=package_files(source)
    old=None
    backup=None
    installed=False
    launcher_touched=False
    launcher=home/'bin'/('art.cmd' if os.name=='nt' else 'art')
    if launcher.exists() and (launcher.is_symlink() or 'ART-CLI managed launcher' not in launcher.read_text(encoding='utf-8')):raise ValueError('Existing art launcher is unmanaged; refusing installation')
    if target.exists():
        if target.is_symlink() or not (target/MARKER).is_file():raise ValueError('Existing target is not a managed ART-CLI install; refusing replacement')
        if not upgrade:raise ValueError('ART-CLI already installed; use --upgrade (keeps backup)')
    prior_launcher=launcher.read_bytes() if launcher.exists() else None
    prior_mode=launcher.stat().st_mode if launcher.exists() else None
    parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.art-cli-stage-',dir=parent))
    manifest={}
    try:
        for path in files:
            relative=path.relative_to(source);dest=staging/relative;dest.parent.mkdir(parents=True,exist_ok=True)
            safe_path(path)
            shutil.copy2(path,dest);manifest[relative.as_posix()]=sha(path)
            if sha(dest)!=manifest[relative.as_posix()]:raise RuntimeError('Copy readback mismatch')
        marker={'name':NAME,'version':'0.2.0','created_at':datetime.now(timezone.utc).isoformat(),'files':manifest}
        (staging/MARKER).write_text(json.dumps(marker,indent=2)+'\n',encoding='utf-8')
        if target.exists():
            backup=home/NAME/'backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup.mkdir(parents=True);old=backup/'plugin';target.rename(old)
        managed_paths(home)
        staging.rename(target)
        installed=True
        for relative,digest in manifest.items():
            if sha(target/relative)!=digest:raise RuntimeError('Installed target readback mismatch')
        bin_dir=home/'bin';bin_dir.mkdir(exist_ok=True)
        launcher=bin_dir/('art.cmd' if os.name=='nt' else 'art')
        if launcher.exists() and 'ART-CLI managed launcher' not in launcher.read_text(encoding='utf-8'):raise ValueError('Existing art launcher is unmanaged; plugin installed but launcher untouched')
        if os.name=='nt':
            py=str(Path(sys.executable)).replace('%','%%');entry=str(target/'art.py').replace('%','%%');profile=str(home).replace('%','%%')
            text=f'@echo off\nrem ART-CLI managed launcher\nsetlocal DisableDelayedExpansion\n"{py}" "{entry}" --home "{profile}" %*\nexit /b %errorlevel%\n'
        else:
            text='#!/bin/sh\n# ART-CLI managed launcher\nexec '+shlex.quote(sys.executable)+' '+shlex.quote(str(target/'art.py'))+' --home '+shlex.quote(str(home))+' "$@"\n'
        managed_paths(home)
        launcher_touched=True
        launcher.write_text(text,encoding='utf-8',newline='\n')
        if launcher.read_bytes()!=text.encode('utf-8'):raise RuntimeError('Launcher readback mismatch')
        if os.name!='nt':launcher.chmod(0o755)
        return {'ok':True,'plugin':str(target),'launcher':str(launcher),'verified_files':len(manifest),'backup':str(old) if old else None,'activation':'Run hermes plugins doctor on this path, then hermes plugins enable art-cli in this profile. Tools load in a new session; no gateway restart.'}
    except BaseException:
        # Roll back every post-swap failure, including hash and launcher errors.
        managed_paths(home)
        if launcher_touched:
            if prior_launcher is None:
                launcher.unlink(missing_ok=True)
            else:
                launcher.write_bytes(prior_launcher)
                launcher.chmod(prior_mode)
        if installed and target.exists():shutil.rmtree(target)
        if old is not None and old.exists():old.rename(target)
        if backup is not None and backup.exists():backup.rmdir()
        raise
    finally:
        if staging.exists():shutil.rmtree(staging)

def status(home):
    target=managed_paths(home)/'plugins'/NAME
    if not (target/MARKER).is_file():return {'ok':True,'installed':False,'plugin':str(target)}
    marker=json.loads((target/MARKER).read_text(encoding='utf-8'));changed=[]
    for rel,digest in marker['files'].items():
        p=Path(rel)
        if p.is_absolute() or '..' in p.parts:raise ValueError('Invalid install manifest path')
        file=target/p
        if not file.is_file() or file.is_symlink() or sha(file)!=digest:changed.append(rel)
    return {'ok':not changed,'installed':True,'plugin':str(target),'verified_files':len(marker['files']),'changed_files':changed}

def uninstall(home):
    home=managed_paths(home);target=home/'plugins'/NAME
    if target.is_symlink() or not (target/MARKER).is_file():raise ValueError('Refusing to remove an unmanaged target')
    # Keep a recoverable copy; never delete app data/config/cache or user documents.
    backup=home/NAME/'backups'/datetime.now(timezone.utc).strftime('uninstalled-%Y%m%dT%H%M%S%fZ')
    backup.mkdir(parents=True);target.rename(backup/'plugin')
    launcher=home/'bin'/('art.cmd' if os.name=='nt' else 'art')
    if launcher.is_file() and 'ART-CLI managed launcher' in launcher.read_text(encoding='utf-8'):launcher.rename(backup/launcher.name)
    return {'ok':not target.exists(),'removed_plugin':str(target),'backup':str(backup),'preserved':'All ART-CLI config/cache/dependencies and user files. Disable art-cli through Hermes before uninstalling.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['install','status','uninstall'])
    parser.add_argument('--home',type=Path,required=True,help='Explicit target Hermes profile home; never guessed')
    parser.add_argument('--source',type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument('--upgrade',action='store_true',help='Back up a previous managed plugin before replacing')
    args=parser.parse_args()
    try:
        result=install(args.source,args.home,args.upgrade) if args.action=='install' else status(args.home) if args.action=='status' else uninstall(args.home)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['ok'] else 1
    except (OSError,ValueError,RuntimeError) as exc:print(json.dumps({'ok':False,'error':str(exc)}));return 1
if __name__=='__main__':raise SystemExit(main())
