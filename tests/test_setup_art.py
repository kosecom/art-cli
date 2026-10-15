"""Portable onboarding contracts; all installation targets are disposable."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import setup_art


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'profile with spaces'

    def invoke(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = setup_art.main(list(args))
        return code, json.loads(output.getvalue())

    def test_default_check_is_read_only_and_never_runs_apps(self):
        with mock.patch('subprocess.Popen', side_effect=AssertionError('no subprocess')), \
             mock.patch.object(setup_art.Store, 'executable', return_value=None) as executable:
            code, report = self.invoke('--home', str(self.home))
        self.assertEqual(code, 0)
        self.assertTrue(report['ok'])
        self.assertEqual(report['action'], 'check')
        self.assertFalse(report['installed'])
        self.assertEqual(executable.call_count, len(setup_art.APPS))
        self.assertFalse(self.home.exists())
        self.assertTrue(report['warnings'])
        self.assertIsNone(report['mcp_config'])

    def test_install_delegates_and_emits_target_scoped_mcp(self):
        plugin = self.home / 'plugins' / 'art-cli'
        def fake_install(source, home, upgrade=False):
            self.assertEqual(source, setup_art.SOURCE)
            self.assertEqual(home, self.home)
            self.assertTrue(upgrade)
            plugin.mkdir(parents=True)
            (plugin / 'art.py').write_text('# fake entry', encoding='utf-8')
            return {'ok': True, 'plugin': str(plugin), 'backup': 'retained-backup'}
        fake = mock.Mock()
        fake.install.side_effect = fake_install
        fake.status.return_value = {'ok': True, 'installed': True}
        with mock.patch.object(setup_art, 'load_installer', return_value=fake), \
             mock.patch.object(setup_art, 'native_platform', return_value='windows'), \
             mock.patch.object(setup_art.Store, 'executable', side_effect=lambda app: Path('/native/photocraft-cli') if app == 'photocraft' else None):
            code, report = self.invoke('--home', str(self.home), '--install', '--upgrade', '--agent', 'mcp')
        self.assertEqual(code, 0)
        self.assertTrue(report['installed'])
        fake.install.assert_called_once()
        fake.status.assert_called_once_with(self.home)
        self.assertEqual(report['installation']['backup'], 'retained-backup')
        server = report['mcp_config']['mcpServers']['art-cli']
        self.assertTrue(Path(server['command']).is_absolute())
        self.assertEqual(server['args'], [str(plugin / 'art.py'), '--home', str(self.home), 'mcp'])
        self.assertTrue(report['apps']['photocraft'])
        self.assertIsNone(report['apps']['vectorcraft'])
        self.assertTrue(report['warnings'])

    def test_argument_and_path_errors_are_json_without_mutation(self):
        cases = [(), ('--home', ''), ('--home', 'relative'),
                 ('--home', str(self.home), '--upgrade'),
                 ('--home', str(self.home), '--activate'),
                 ('--home', str(self.home), '--install', '--activate', '--agent', 'mcp'),
                 ('--home', str(self.home), '--check', '--install'),
                 ('--home', str(self.home), '--agent', 'unknown'),
                 ('--home', '\x00bad')]
        for args in cases:
            with self.subTest(args=args):
                code, report = self.invoke(*args)
                self.assertEqual(code, 2)
                self.assertFalse(report['ok'])
                self.assertFalse(self.home.exists())
        blocker = Path(self.temp.name) / 'file'
        blocker.write_text('unchanged', encoding='utf-8')
        for home in (blocker, blocker / 'child'):
            code, report = self.invoke('--home', str(home), '--install')
            self.assertEqual(code, 2)
        self.assertEqual(blocker.read_text(encoding='utf-8'), 'unchanged')

    def test_unsupported_install_fails_but_check_works(self):
        with mock.patch.object(setup_art, 'native_platform', return_value='unsupported'), \
             mock.patch.object(setup_art.Store, 'executable', return_value=None):
            code, report = self.invoke('--home', str(self.home), '--install')
            self.assertEqual(code, 2)
            self.assertFalse(self.home.exists())
            code, report = self.invoke('--home', str(self.home), '--check')
            self.assertEqual(code, 0)

    def test_fake_package_install_upgrade_and_check_preserve_config(self):
        source = Path(self.temp.name) / 'source'
        source.mkdir()
        for name, text in {'plugin.yaml': 'name: art-cli\n', '__init__.py': '',
                           'art.py': '# fixture\n', 'art_cli/api.py': '# fixture\n'}.items():
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        self.home.mkdir()
        config = self.home / 'config.yaml'
        original = b'# preserve comments\nplugins:\n  enabled: [other]\nmodel: untouched\n'
        config.write_bytes(original)
        installer = setup_art.load_installer()
        with mock.patch.object(setup_art, 'SOURCE', source), \
             mock.patch.object(setup_art, 'load_installer', return_value=installer), \
             mock.patch.object(setup_art, 'native_platform', return_value='windows'), \
             mock.patch.object(setup_art.Store, 'executable', return_value=None), \
             mock.patch('subprocess.Popen', side_effect=AssertionError('no process')):
            code, report = self.invoke('--home', str(self.home), '--install', '--agent', 'hermes', '--activate')
            self.assertEqual(code, 3)
            self.assertTrue(report['installed'])
            self.assertFalse(report['ok'])
            self.assertEqual(report['activation']['status'], 'manual_required')
            self.assertFalse(report['activation']['performed'])
            self.assertEqual(report['activation']['environment']['HERMES_HOME'], str(self.home))
            self.assertEqual(report['activation']['command'], ['hermes', 'plugins', 'enable', 'art-cli'])
            code, report = self.invoke('--home', str(self.home), '--install')
            self.assertEqual(code, 1)
            code, report = self.invoke('--home', str(self.home), '--install', '--upgrade')
            self.assertEqual(code, 0)
            self.assertTrue(Path(report['installation']['backup']).is_dir())
            before = {str(p.relative_to(self.home)): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
            code, report = self.invoke('--home', str(self.home), '--check')
            self.assertEqual(code, 0)
            after = {str(p.relative_to(self.home)): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
            self.assertEqual(before, after)
            (self.home / 'plugins/art-cli/art.py').write_text('tampered', encoding='utf-8')
            code, report = self.invoke('--home', str(self.home), '--check')
            self.assertEqual(code, 1)
            self.assertFalse(report['installed'])
            self.assertIsNone(report['mcp_config'])
        self.assertEqual(config.read_bytes(), original)

    def test_invalid_store_is_reported_before_install(self):
        (self.home / 'art-cli').mkdir(parents=True)
        (self.home / 'art-cli/config.json').write_text('{broken', encoding='utf-8')
        with mock.patch.object(setup_art, 'load_installer') as installer:
            code, report = self.invoke('--home', str(self.home), '--install')
        self.assertEqual(code, 1)
        self.assertFalse(report['ok'])
        installer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
