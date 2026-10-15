#!/usr/bin/env python3
"""Explicit-home, offline ART-CLI onboarding. Checks never launch native apps."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import shlex
import shutil
import sys

# Even a check must not leave import caches in the source or target tree.
sys.dont_write_bytecode = True
from art_cli.config import APPS, Store, native_platform  # noqa: E402

SOURCE = Path(__file__).resolve().parent


def load_installer():
    """Load the sibling installer, never an unrelated module named install."""
    spec = importlib.util.spec_from_file_location('_art_onboarding_installer', SOURCE / 'install.py')
    if spec is None or spec.loader is None:
        raise RuntimeError('Cannot load the packaged installer')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UsageError(ValueError):
    """Invalid arguments, platform, or target path (exit 2)."""


class JsonParser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


def target_home(value):
    if not value.strip() or '\x00' in value:
        raise UsageError('--home must be a nonempty absolute directory path')
    home = Path(value).expanduser()
    if not home.is_absolute():
        raise UsageError('--home must be an absolute path (not a profile name)')
    # Preserve symlinks for the installer's own safety validation.
    if '..' in home.parts:
        raise UsageError('--home must not contain parent-directory components')
    for part in (home, *home.parents):
        if part.exists() and not part.is_dir():
            raise UsageError('--home or an ancestor is not a directory')
    return home


def activation_instructions(home, requested):
    """Defer consent and config migration to the supported Hermes CLI."""
    path = str(home)
    return {
        'status': 'manual_required', 'performed': False, 'requested': requested,
        'active': None, 'runtime_on_path': shutil.which('hermes') is not None,
        'command': ['hermes', 'plugins', 'enable', 'art-cli'],
        'environment': {'HERMES_HOME': path},
        'posix_command': 'HERMES_HOME=' + shlex.quote(path) + ' hermes plugins enable art-cli',
        'powershell_command': "$env:HERMES_HOME = '" + path.replace("'", "''") + "'; hermes plugins enable art-cli",
        'reason': 'Activation is not automated; use a fresh terminal with the exact target home. '
                  'The Hermes CLI owns plugin consent and configuration. Current activation is not inspected.',
    }


def run(args):
    home = target_home(args.home)
    if args.upgrade and not args.install:
        raise UsageError('--upgrade requires --install')
    if args.activate and (not args.install or args.agent != 'hermes'):
        raise UsageError('--activate requires --install --agent hermes')
    if args.install and native_platform() not in ('windows', 'mac'):
        raise UsageError('Installation requires native Windows or macOS')
    store = Store(home)
    apps = {name: str(path) if (path := store.executable(name)) else None for name in APPS}
    installer = load_installer()
    installation = installer.install(SOURCE, home, upgrade=args.upgrade) if args.install else None
    status = installer.status(home)
    installed = bool(status.get('installed') and status.get('ok'))
    entry = home / 'plugins' / 'art-cli' / 'art.py'
    missing = [name for name, path in apps.items() if not path]
    interpreter = str(Path(sys.executable).absolute())
    command = [interpreter, str(entry), '--home', str(home)] if installed else None
    ok = bool(status.get('ok')) and (not args.install or installed)
    if installation is not None:
        ok = ok and bool(installation.get('ok'))
    warnings = ['Missing native CLIs: ' + ', '.join(missing)] if missing else []
    if args.agent == 'hermes':
        warnings.append('Plugin activation was not performed or verified by this helper.')
    report = {
        'ok': ok and not args.activate, 'action': 'install' if args.install else 'check',
        'home': str(home), 'agent': args.agent, 'installed': installed,
        'installation': installation, 'status': status,
        'apps': apps, 'warnings': warnings, 'cli_command': command,
        'activation': activation_instructions(home, args.activate) if args.agent == 'hermes' else None,
        'mcp_config': {'mcpServers': {'art-cli': {'command': interpreter,
                       'args': [str(entry), '--home', str(home), 'mcp']}}} if installed else None,
        'downloads': {
            'performed': False,
            'guidance': 'Native apps are optional and installed separately. To stage an official CLI, '
                        'explicitly run bootstrap.py --app APP --version PINNED_VERSION --target NEW_DIRECTORY. '
                        'Review the version and download before running; setup never invokes bootstrap.py.',
        },
    }
    return report, (1 if not ok else 3 if args.activate else 0)


def main(argv=None):
    parser = JsonParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--home', required=True, help='Absolute target home; never inferred')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--check', action='store_true', help='Read-only inspection (default)')
    action.add_argument('--install', action='store_true', help='Explicitly install the local package')
    parser.add_argument('--upgrade', action='store_true', help='Installer-managed backup and replacement')
    parser.add_argument('--agent', choices=('hermes', 'mcp', 'cli'), default='cli')
    parser.add_argument('--activate', action='store_true', help='Request Hermes activation; currently returns manual instructions, exit 3')
    try:
        args = parser.parse_args(argv)
        report, code = run(args)
    except UsageError as exc:
        report, code = {'ok': False, 'error': str(exc), 'error_type': 'usage'}, 2
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, ImportError) as exc:
        report, code = {'ok': False, 'error': str(exc), 'error_type': type(exc).__name__}, 1
    report['exit_code'] = code
    print(json.dumps(report, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
