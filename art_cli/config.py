"""Profile-aware storage and trusted, platform-native executable discovery."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
from .rpc import canonical,strict_json

APPS={name.lower():name for name in ('PhotoCraft','VectorCraft','FilmCraft','LightCraft','PdfCraft','EffectCraft','DesignCraft','WordCraft','DeckCraft','GridCraft','CADCraft','SoundCraft','FigCraft')}


def native_platform():
    if os.name=='nt':return 'windows'
    if sys.platform=='darwin':return 'mac'
    return 'unsupported'


def profile_home():
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home())
    except ImportError:
        if os.environ.get('HERMES_HOME'):return Path(os.environ['HERMES_HOME']).expanduser()
        if os.name=='nt':return Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'hermes'
        return Path.home()/'.hermes'


def require_app(app):
    if not isinstance(app,str) or app not in APPS:raise ValueError('Unknown ArtCraft app; use catalog for exact identifiers')
    return app


def atomic_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as stream:
            stream.write(canonical(value)+'\n');stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
    finally:
        try:os.unlink(tmp)
        except FileNotFoundError:pass


class Store:
    def __init__(self,home=None):
        self.home=Path(home).expanduser().resolve() if home is not None else profile_home().resolve()
        self.root=self.home/'art-cli'
        path=self.root/'config.json'
        self.config=strict_json(path.read_text(encoding='utf-8')) if path.exists() else {'version':1}
        if not isinstance(self.config,dict) or self.config.get('version',1)!=1:raise ValueError('Unsupported ART-CLI config version')
        for key in ('apps','remotes'):
            if not isinstance(self.config.get(key,{}),dict):raise ValueError('Invalid operator configuration: '+key)

    def executable(self,app):
        require_app(app)
        setting=self.config.get('apps',{}).get(app,{})
        if not isinstance(setting,dict):raise ValueError('Invalid app configuration')
        suffix='.exe' if os.name=='nt' else ''
        basename=app+'-cli'+suffix
        if 'executable' in setting:
            path=Path(setting['executable']).expanduser()
            if not path.is_absolute() or path.name.lower()!=basename:raise ValueError('Configured executable must be an absolute path to '+basename)
            return path if path.is_file() else None
        name=APPS[app]
        if native_platform()=='windows':
            roots=[Path(os.environ.get('ProgramFiles','C:/Program Files')),Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'Programs']
            candidates=[base/name/basename for base in roots]
        elif native_platform()=='mac':
            candidates=[]
            for base in (Path('/Applications'),Path.home()/'Applications'):
                for sub in ('MacOS','Resources','Helpers'):
                    candidates.append(base/(name+'.app')/'Contents'/sub/basename)
            candidates += [self.root/'bin'/basename,Path.home()/'.local/share/artcraft/cli'/basename,Path.home()/'.local/bin'/basename]
        else:
            candidates=[]
        found=shutil.which(basename)
        if found:candidates.append(Path(found))
        return next((p.absolute() for p in candidates if p.is_file()),None)

    def command(self,app,mode='headless'):
        exe=self.executable(app)
        if exe is None:raise FileNotFoundError(f'{app} CLI not installed on {native_platform()}; see guide installation')
        if mode=='headless':
            args=['mcp']+(['--headless'] if app=='vectorcraft' else [])
            automation=self.config.get('apps',{}).get(app,{}).get('automation',{})
            if automation:
                if app!='photocraft' or not isinstance(automation,dict) or set(automation)-{'read_root','write_root'}:raise ValueError('Unsupported operator automation roots; consult native app guide')
                for field,flag in [('read_root','--automation-read-root'),('write_root','--automation-write-root')]:
                    if field in automation:
                        root=Path(automation[field]).expanduser()
                        if not root.is_absolute() or not root.is_dir():raise ValueError('Automation root must be an explicit existing absolute directory')
                        args.extend([flag,root.as_posix()])
        else:
            modes=self.config.get('apps',{}).get(app,{}).get('modes',{})
            if mode not in modes:raise ValueError(f'No operator-configured {mode!r} mode for {app}; headless does not attach to the GUI')
            args=modes[mode].get('args') if isinstance(modes[mode],dict) else modes[mode]
            if not isinstance(args,list) or not args or not all(isinstance(a,str) and '\x00' not in a for a in args):raise ValueError('Invalid native mode argv')
        return [str(exe),*args]

    def identity(self,app,mode='headless',digest=False):
        exe=self.executable(app)
        if exe is None:return None
        stat=exe.stat()
        ident={'path':str(exe),'size':stat.st_size,'mtime_ns':stat.st_mtime_ns,'platform':native_platform(),'mode':mode,'configuration_sha256':hashlib.sha256(canonical(self.command(app,mode)).encode('utf-8')).hexdigest()}
        if digest:
            sha=hashlib.sha256()
            with exe.open('rb') as file:
                for block in iter(lambda:file.read(1024*1024),b''):sha.update(block)
            ident['sha256']=sha.hexdigest()
        return ident

    def cache_path(self,app,mode='headless'):
        require_app(app)
        if not isinstance(mode,str) or not mode or not all(c.isalnum() or c in '-_' for c in mode):raise ValueError('Invalid mode identifier')
        return self.root/'cache'/native_platform()/(app+'-'+mode+'.json')

    def cached(self,app,mode='headless'):
        path=self.cache_path(app,mode)
        if not path.is_file():return None
        try:
            value=strict_json(path.read_text(encoding='utf-8'))
            if not isinstance(value,dict):return None
            stored=value.get('identity',{})
            if not isinstance(stored,dict) or 'command' in stored:return None
            current=self.identity(app,mode,digest=True)
            if current is None:return None
            if any(stored.get(k)!=v for k,v in current.items()):return None
            return value
        except (OSError,ValueError,TypeError):return None

    def save(self,app,value,mode='headless'):atomic_json(self.cache_path(app,mode),value)

    def route(self,platform):
        if platform in (None,'local',native_platform()):return None
        route=self.config.get('remotes',{}).get(platform)
        if not isinstance(route,dict) or not isinstance(route.get('command'),list) or not route['command'] or not all(isinstance(x,str) and x and '\x00' not in x for x in route['command']):
            raise ValueError(f'No trusted remote route configured for {platform!r}; never falling back to another host')
        return route
