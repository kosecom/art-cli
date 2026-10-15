"""Explicit official dependency staging. Never changes installed apps or runtime routes."""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib,json,os
from pathlib import Path,PurePosixPath
import platform,re,stat,subprocess,urllib.request,zipfile
from .config import APPS,native_platform,require_app


def fetch(url,limit=512*1024*1024):
    request=urllib.request.Request(url,headers={'User-Agent':'hermes-art-cli/0.2.0','Accept':'application/octet-stream' if '/releases/download/' in url else 'application/vnd.github+json'})
    with urllib.request.urlopen(request,timeout=180) as response:
        data=response.read(limit+1)
        if len(data)>limit:raise ValueError('Official asset exceeds download limit')
        return data


def digest(data):return hashlib.sha256(data).hexdigest()


def stage(app,version,target):
    require_app(app)
    if not isinstance(version,str) or not re.fullmatch(r'\d+\.\d+\.\d+',version):raise ValueError('Exact released major.minor.patch version required')
    target=Path(target).expanduser().absolute()
    if target.exists():raise ValueError('Dependency stage target must be new; never overwrite a runtime')
    host=native_platform()
    if host not in ('windows','mac'):raise ValueError('Stage natively on Windows or macOS')
    arch=platform.machine().lower()
    if host=='windows':
        arch={'amd64':'x64','x86_64':'x64','arm64':'arm64','aarch64':'arm64','x86':'x86','i386':'x86'}.get(arch)
        if not arch:raise ValueError('Unknown Windows architecture')
        asset_name=f'{app}-{version}-windows-{arch}-portable.zip'
    else:asset_name=f'{app}-cli-{version}-macos-universal.zip'
    base=f'https://github.com/storytold/{app}/releases/download/v{version}/'
    api=f'https://api.github.com/repos/storytold/{app}/releases/tags/v{version}'
    release=json.loads(fetch(api,4*1024*1024))
    if release.get('tag_name')!='v'+version or release.get('draft'):raise ValueError('Unexpected release identity')
    asset=next((a for a in release['assets'] if a['name']==asset_name),None)
    sums=next((a for a in release['assets'] if a['name']=='SHA256SUMS.txt'),None)
    if asset is None or sums is None:raise ValueError('Matching official native asset/checksums not published; no guessed substitute')
    for entry in (asset,sums):
        if entry['browser_download_url']!=base+entry['name']:raise ValueError('Unexpected release download URL')
    checksums=fetch(sums['browser_download_url'],1024*1024)
    if sums.get('digest') and sums['digest']!='sha256:'+digest(checksums):raise ValueError('Checksum asset digest mismatch')
    published={line.split()[-1].lstrip('*'):line.split()[0] for line in checksums.decode('utf-8').splitlines() if len(line.split())>=2}
    data=fetch(asset['browser_download_url'])
    actual=digest(data)
    if len(data)!=asset['size'] or published.get(asset_name)!=actual:raise ValueError('Official archive size/checksum mismatch')
    if asset.get('digest') and asset['digest']!='sha256:'+actual:raise ValueError('GitHub asset digest mismatch')
    target.mkdir(parents=True)
    archive=target/asset_name;archive.write_bytes(data)
    if digest(archive.read_bytes())!=actual:raise ValueError('Archive disk readback mismatch')
    with zipfile.ZipFile(archive) as zipped:
        members=zipped.infolist()
        if len(members)>20000 or sum(m.file_size for m in members)>2*1024*1024*1024:raise ValueError('Archive expansion limit exceeded')
        for member in members:
            path=PurePosixPath(member.filename);mode=member.external_attr>>16
            if path.is_absolute() or '..' in path.parts or '\\' in member.filename or ':' in member.filename or stat.S_ISLNK(mode):raise ValueError('Unsafe archive member')
        zipped.extractall(target/'extracted')
    expected=app+'-cli'+('.exe' if host=='windows' else '')
    binaries=list((target/'extracted').rglob(expected))
    if len(binaries)!=1:raise ValueError('Expected one official native CLI')
    binary=binaries[0]
    signature=None
    if host=='mac':
        binary.chmod(binary.stat().st_mode|0o111)
        proc=subprocess.run(['/usr/bin/codesign','--verify','--strict',str(binary)],capture_output=True,timeout=30)
        if proc.returncode:raise ValueError('Native Mac signature validation failed; no bypass')
        signature='codesign --verify --strict passed; no notarization claim'
    manifest={'app':app,'version':version,'platform':host,'created_at':datetime.now(timezone.utc).isoformat(),'release_url':release['html_url'],'asset_url':asset['browser_download_url'],'archive_sha256':actual,'published_sha256':published[asset_name],'github_digest':asset.get('digest'),'binary':str(binary),'binary_sha256':digest(binary.read_bytes()),'signature_check':signature,'runtime_changed':False}
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    return manifest
