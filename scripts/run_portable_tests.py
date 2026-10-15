"""Portable contract suite; reports the real-Hermes adapter as skipped if absent."""
from pathlib import Path
import importlib.util
import os
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    base = Path(os.environ.get('TMPDIR', str(ROOT.parent))).resolve()
    if base == ROOT or ROOT in base.parents:
        base = ROOT.parent.resolve()
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(base.resolve())) as tmp:
        tempfile.tempdir = tmp
        for name in ('TMPDIR', 'TMP', 'TEMP'):
            os.environ[name] = tmp
        suite = unittest.TestSuite()
        loader = unittest.TestLoader()
        for path in sorted((ROOT / 'tests').glob('test_*.py')):
            if path.name == 'test_plugin_adapter.py' and importlib.util.find_spec('hermes_cli') is None:
                @unittest.skip('Real Hermes runtime unavailable: adapter suite not executed')
                def missing_runtime():
                    pass
                suite.addTest(unittest.FunctionTestCase(missing_runtime))
            else:
                suite.addTests(loader.discover(str(ROOT / 'tests'), pattern=path.name))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
