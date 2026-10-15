"""Contract tests use synthetic peers, never call user applications."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

class DiscoveryContract(unittest.TestCase):
    def test_catalog_never_starts_a_process(self):
        from art_cli.api import dispatch
        with tempfile.TemporaryDirectory() as tmp, patch('subprocess.Popen',side_effect=AssertionError('eager worker')):
            result=dispatch('catalog',{},home=Path(tmp))
        self.assertTrue(result['ok'])
        self.assertEqual(len(result['apps']),13)

    def test_unknown_app_is_not_an_executable(self):
        from art_cli.api import dispatch
        with tempfile.TemporaryDirectory() as tmp, patch('subprocess.Popen',side_effect=AssertionError('spawned')):
            result=dispatch('execute',{'app':'../../python','tool':'anything'},home=Path(tmp))
        self.assertFalse(result['ok'])

    def test_missing_platform_route_fails_closed(self):
        from art_cli.api import dispatch
        from art_cli.config import native_platform
        other='mac' if native_platform()=='windows' else 'windows'
        with tempfile.TemporaryDirectory() as tmp, patch('subprocess.Popen',side_effect=AssertionError('spawned')):
            result=dispatch('catalog',{'platform':other},home=Path(tmp))
        self.assertFalse(result['ok'])
        self.assertIn('route',result['error']['message'].lower())

    def test_duplicate_json_keys_are_rejected(self):
        from art_cli.rpc import strict_json
        with self.assertRaises(ValueError):strict_json('{"a":1,"a":2}')

    def test_batch_is_validated_before_spawn(self):
        from art_cli.api import dispatch
        with tempfile.TemporaryDirectory() as tmp, patch('subprocess.Popen',side_effect=AssertionError('spawned')):
            result=dispatch('batch',{'steps':[{'app':'cadcraft','tool':'inspect_drawing'},{'app':'unknown','tool':'x'}]},home=Path(tmp))
        self.assertFalse(result['ok'])

    def test_help_and_guide_do_not_spawn(self):
        from art_cli.api import dispatch
        with tempfile.TemporaryDirectory() as tmp, patch('subprocess.Popen',side_effect=AssertionError('spawned')):
            result=dispatch('guide',{},home=Path(tmp))
        self.assertTrue(result['ok'])
        self.assertIn('save',result['guide'].lower())

if __name__=='__main__':unittest.main()
