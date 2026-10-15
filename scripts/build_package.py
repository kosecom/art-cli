"""Build a portable source ZIP from an explicit allowlist; never include runtime data."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--label',default='candidate');args=parser.parse_args()
    if not re.fullmatch('[a-zA-Z0-9_-]+',args.label):raise ValueError('Invalid package label')
    spec=importlib.util.spec_from_file_location('art_package_installer',ROOT/'install.py')
    installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
    paths=[p for p in installer.package_files(ROOT) if p.name!='BUILD-MANIFEST.json']
    paths += sorted((ROOT/'tests').rglob('*.py'))
    paths += [ROOT/'scripts'/name for name in ('build_package.py','run_portable_tests.py','smoke_test.py') if (ROOT/'scripts'/name).is_file()]
    # No profiles, caches, archives, vendor binaries, research, screenshots, secrets or live evidence.
    files={}
    for path in sorted(set(paths)):
        relative=path.relative_to(ROOT).as_posix()
        if any(part in {'private-qa-home','evidence','research','__pycache__','.git'} for part in path.relative_to(ROOT).parts):raise ValueError('Forbidden package source')
        if path.is_symlink():raise ValueError('Package source is a symlink')
        data=path.read_bytes()
        # Concrete environment identifiers must never become portable defaults/report content.
        text=data.decode('utf-8',errors='ignore')
        forbidden_patterns=(r'(?:[A-Za-z]:[/\\\\]Users[/\\\\]|/Users/|/home/)[A-Za-z0-9_.-]+',
                            r'gh[pousr]_[A-Za-z0-9]{30,}', r'github_pat_[A-Za-z0-9_]{30,}',
                            r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')
        if any(re.search(pattern,text) for pattern in forbidden_patterns):raise ValueError('Private machine value or credential in package source: '+relative)
        files[relative]=data
    manifest={'name':'art-cli','version':'0.2.0','status':args.label,'built_at':datetime.now(timezone.utc).isoformat(),'files':{name:{'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)} for name,data in sorted(files.items())}}
    files['BUILD-MANIFEST.json']=(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n').encode('utf-8')
    out=ROOT/'dist';out.mkdir(exist_ok=True)
    destination=out/('ART-CLI-0.2.0-'+args.label+'.zip')
    if destination.exists():raise ValueError('Refusing to overwrite an existing package artifact')
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as zipped:
        for name,data in sorted(files.items()):zipped.writestr('art-cli/'+name,data)
    with zipfile.ZipFile(destination) as zipped:
        if set(zipped.namelist())!={'art-cli/'+name for name in files}:raise ValueError('Package member mismatch')
        if zipped.testzip() is not None:raise ValueError('Package CRC mismatch')
        for name,data in files.items():
            if zipped.read('art-cli/'+name)!=data:raise ValueError('Package byte readback mismatch')
    checksum=hashlib.sha256(destination.read_bytes()).hexdigest()
    report={'file':str(destination),'sha256':checksum,'bytes':destination.stat().st_size,'source_files':len(manifest['files']),'zip_members':len(files),'status':args.label,'private_data_scan':'passed','zip_readback':'exact'}
    (out/(destination.name+'.json')).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    (out/(destination.name+'.sha256')).write_text(checksum+'  '+destination.name+'\n',encoding='ascii')
    print(json.dumps(report))
if __name__=='__main__':main()
