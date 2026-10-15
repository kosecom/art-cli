"""Both metadata cache readers must verify executable content and provenance."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from art_cli.config import Store, atomic_json
from art_cli.commands import cached_commands, cache_path


class CommandCacheReviewTests(unittest.TestCase):
    def check_cache(self, legacy=False):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            exe = Path(folder) / 'dummy.exe'
            exe.write_bytes(b'original')
            with patch.object(store, 'executable', return_value=exe), patch.object(store, 'command', return_value=[str(exe), 'mcp']):
                identity = store.identity('figcraft', digest=True)
                if legacy:
                    identity['command'] = [str(exe), 'mcp']
                data = {'identity': identity, 'commands': [{'id': 'old'}], 'tools': []}
                store.save('figcraft', data)
                path = cache_path(store, 'figcraft', 'headless')
                atomic_json(path, data)
                if not legacy:
                    self.assertIsNotNone(store.cached('figcraft'))
                    self.assertIsNotNone(cached_commands(store, 'figcraft'))
                    before = exe.stat()
                    exe.write_bytes(b'mutated!')
                    os.utime(exe, ns=(before.st_atime_ns, before.st_mtime_ns))
                    self.assertEqual(exe.stat().st_mtime_ns, before.st_mtime_ns)
                    self.assertEqual(exe.stat().st_size, before.st_size)
                self.assertIsNone(store.cached('figcraft'))
                self.assertIsNone(cached_commands(store, 'figcraft'))
                self.assertTrue(path.is_file())
                self.assertTrue(store.cache_path('figcraft').is_file())

    def test_same_stat_binary_invalidates_both_caches(self):
        self.check_cache()

    def test_matching_identity_with_legacy_command_rejected(self):
        self.check_cache(legacy=True)
