"""The JSON CLI wire encoding must not depend on a Windows console code page."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CliEncodingTests(unittest.TestCase):
    def test_guide_json_is_utf8_even_with_legacy_stdio_encoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, PYTHONUTF8='0', PYTHONIOENCODING='cp1252')
            result = subprocess.run([sys.executable, str(ROOT / 'art.py'),
                                     '--home', tmp, 'guide'], capture_output=True,
                                    env=env, timeout=10)
        self.assertEqual(result.returncode, 0)
        parsed = json.loads(result.stdout.decode('utf-8'))
        self.assertTrue(parsed['ok'])
        self.assertIn('ART-CLI', parsed['guide'])


if __name__ == '__main__':
    unittest.main()
