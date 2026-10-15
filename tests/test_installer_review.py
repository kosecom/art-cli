"""Installer regression tests use only disposable synthetic packages."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import install as installer


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


class InstallerReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root / 'source'
        for name in ('plugin.yaml', '__init__.py', 'art.py', 'art_cli/api.py'):
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('original', encoding='utf-8')
        self.home = self.root / 'home'

    def link(self, path, target):
        try:
            path.symlink_to(target, target_is_directory=True)
        except OSError:
            if os.name != 'nt':
                self.skipTest('Directory symlinks unavailable')
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(path), str(target)], capture_output=True)
            if result.returncode:
                self.skipTest('Directory junction creation unavailable')
        def remove_link():
            if path.is_symlink():
                path.unlink()
            elif path.exists() or getattr(path, 'is_junction', lambda: False)():
                os.rmdir(path)
        self.addCleanup(remove_link)

    def test_source_directory_link_rejected(self):
        real = self.root / 'real'
        (self.source / 'art_cli').rename(real)
        self.link(self.source / 'art_cli', real)
        with self.assertRaises(ValueError):
            installer.install(self.source, self.home)
        self.assertFalse(self.home.exists())

    def test_source_root_ancestor_link_rejected(self):
        alias = self.root / 'alias'
        self.link(alias, self.source)
        with self.assertRaises(ValueError):
            installer.install(alias, self.home)

    @unittest.skipUnless(os.name == 'nt', 'Windows junction regression')
    def test_real_windows_junction_is_rejected(self):
        alias = self.root / 'junction'
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(self.source)], capture_output=True)
        if result.returncode:
            self.skipTest('Junction creation unavailable')
        self.addCleanup(lambda: os.rmdir(alias))
        with self.assertRaises(ValueError):
            installer.install(alias, self.home)
        self.assertFalse(self.home.exists())

    def test_destination_ancestor_links_rejected_without_mutation(self):
        for relative in ('plugins', 'bin', 'art-cli/backups'):
            with self.subTest(relative=relative):
                home = self.root / relative.replace('/', '-')
                external = self.root / ('outside-' + relative.replace('/', '-'))
                external.mkdir()
                (external / 'foreign').write_bytes(b'untouched')
                link = home / relative
                link.parent.mkdir(parents=True, exist_ok=True)
                self.link(link, external)
                before = snapshot(external)
                with self.assertRaises(ValueError):
                    installer.install(self.source, home)
                self.assertEqual(before, snapshot(external))

    def test_late_launcher_failure_restores_exact_prior_install(self):
        installer.install(self.source, self.home)
        target = self.home / 'plugins/art-cli'
        launcher = self.home / 'bin' / ('art.cmd' if os.name == 'nt' else 'art')
        (target / 'foreign.txt').write_bytes(b'keep foreign plugin content')
        (self.home / 'art-cli/config.json').parent.mkdir(exist_ok=True)
        (self.home / 'art-cli/config.json').write_bytes(b'keep operator data')
        prior = snapshot(self.home)
        (self.source / 'art.py').write_text('updated', encoding='utf-8')
        original = Path.write_text
        def fail(path, *args, **kwargs):
            if path == launcher:
                path.write_bytes(b'partial launcher write')
                raise OSError('Injected late launcher failure')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'write_text', fail):
            with self.assertRaises(OSError):
                installer.install(self.source, self.home, upgrade=True)
        self.assertEqual(snapshot(self.home), prior)

    def test_late_hash_failure_restores_prior_install(self):
        installer.install(self.source, self.home)
        prior = snapshot(self.home)
        original = installer.sha
        def fail(path):
            if self.home / 'plugins/art-cli' in path.parents:
                raise OSError('Injected late readback failure')
            return original(path)
        with patch.object(installer, 'sha', fail):
            with self.assertRaises(OSError):
                installer.install(self.source, self.home, upgrade=True)
        self.assertEqual(snapshot(self.home), prior)
