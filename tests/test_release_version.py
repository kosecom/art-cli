"""Release metadata must agree across distributable entrypoints."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ReleaseVersionTests(unittest.TestCase):
    def test_public_release_version_is_consistent(self):
        from art_cli import __version__
        self.assertEqual(__version__, '0.2.0')
        for relative in ('plugin.yaml', 'pyproject.toml', 'install.py',
                         'art_cli/worker.py', 'art_cli/rpc.py', 'art_cli/dependencies.py'):
            text = (ROOT / relative).read_text(encoding='utf-8')
            with self.subTest(path=relative):
                self.assertIn('0.2.0', text)
                self.assertNotIn('0.1.0', text)


if __name__ == '__main__':
    unittest.main()
