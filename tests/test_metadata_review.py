"""Synthetic regression coverage for public metadata and credential guards."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from art_cli.config import Store, atomic_json
from art_cli.control import ControlError, _no_secret, call_control


class MetadataReviewTests(unittest.TestCase):
    def test_identity_and_legacy_cache_never_publish_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            exe = Path(tmp) / 'binary'
            exe.write_bytes(b'original')
            argv = ['mcp', '--token', 'synthetic-' + chr(34) + 'value']
            with patch.object(store, 'executable', return_value=exe), patch.object(store, 'command', return_value=argv):
                identity = store.identity('figcraft', 'gui', digest=True)
                self.assertNotIn('command', identity)
                self.assertNotIn(argv[-1], json.dumps(identity, ensure_ascii=False))
                store.save('figcraft', {'identity': identity}, 'gui')
                self.assertIsNotNone(store.cached('figcraft', 'gui'))
                legacy = dict(identity, command=argv)
                atomic_json(store.cache_path('figcraft', 'gui'), {'identity': legacy})
                self.assertIsNone(store.cached('figcraft', 'gui'))

    def test_command_and_same_stat_binary_changes_invalidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            exe = Path(tmp) / 'binary'
            exe.write_bytes(b'original')
            with patch.object(store, 'executable', return_value=exe), patch.object(store, 'command', return_value=['mcp']):
                store.save('figcraft', {'identity': store.identity('figcraft', digest=True)})
                with patch.object(store, 'command', return_value=['mcp', '--changed']):
                    self.assertIsNone(store.cached('figcraft'))
                before = exe.stat()
                exe.write_bytes(b'mutated!')
                os.utime(exe, ns=(before.st_atime_ns, before.st_mtime_ns))
                self.assertIsNone(store.cached('figcraft'))

    def test_escaped_secrets_in_values_keys_and_native_text(self):
        for secret in ['test' + chr(34) + 'quote', 'test\\slash', 'test\x01control']:
            for payload in [{'nested': [secret]}, {secret: 'value'}, {'content': [{'text': json.dumps({'echo': secret})}]}]:
                with self.assertRaises(ControlError):
                    _no_secret(payload, secret)
        self.assertEqual(_no_secret({'text': 'ordinary'}, 'different'), {'text': 'ordinary'})

    def test_public_catalog_doctor_refresh_and_configuration_errors(self):
        from art_cli.api import dispatch
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            exe = Path(tmp) / ('figcraft-cli.exe' if os.name == 'nt' else 'figcraft-cli')
            exe.write_bytes(b'placeholder')
            secret = 'synthetic-' + chr(34) + '\\opaque'
            config = {'version': 1, 'apps': {'figcraft': {'executable': str(exe), 'modes': {'gui': ['mcp', '--token', secret]}}}}
            atomic_json(store.root / 'config.json', config)
            with patch('art_cli.api.Session') as session:
                native = session.return_value.__enter__.return_value
                native.collect.return_value = []
                native.info = {}
                result = dispatch('refresh', {'app': 'figcraft', 'mode': 'gui', 'commands': False}, home=tmp)
                self.assertTrue(result['ok'])
                public = [result]
                for operation in ('catalog', 'doctor'):
                    for args in ({'mode': 'gui'}, {'app': 'figcraft', 'mode': 'gui'}):
                        public.append(dispatch(operation, args, home=tmp))
                cache_text = store.cache_path('figcraft', 'gui').read_text(encoding='utf-8')
                config['apps']['figcraft']['modes']['gui'].append(None)
                atomic_json(store.root / 'config.json', config)
                public.append(dispatch('refresh', {'app': 'figcraft', 'mode': 'gui', 'commands': False}, home=tmp))
                encoded = json.dumps(public) + cache_text
                self.assertFalse(secret in encoded or json.dumps(secret)[1:-1] in encoded, 'Public metadata disclosed an operator argument')
                self.assertFalse(public[-1]['ok'])

    def test_request_guard_prevents_transport_for_escaped_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            store.config = {'apps': {'photocraft': {'control': {'transport': 'tcp-jsonl', 'endpoint': {'host': '127.0.0.1', 'port': 12345}, 'token_file': 'unused'}}}}
            secret = 'test' + chr(34) + '\\value'
            with patch('art_cli.control._private_file', return_value=secret), patch('art_cli.control._tcp', return_value={'ok': True}) as transport:
                with self.assertRaises(ControlError):
                    call_control(store, {'app': 'photocraft', 'method': 'read', 'params': {'content': json.dumps({'echo': secret})}})
                transport.assert_not_called()
