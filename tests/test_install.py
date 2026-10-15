"""Portable install/upgrade/uninstall tests use isolated profile homes only."""
import importlib.util,json,os
from pathlib import Path
import subprocess,sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('art_installer_test',ROOT/'install.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)

class InstallerTests(unittest.TestCase):
    def test_install_readback_cli_upgrade_and_uninstall(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)/'profile with spaces'
            result=installer.install(ROOT,home);self.assertTrue(result['ok']);self.assertTrue(installer.status(home)['ok'])
            proc=subprocess.run([sys.executable,str(home/'plugins/art-cli/art.py'),'--home',str(home),'guide'],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(proc.returncode,0);self.assertTrue(json.loads(proc.stdout)['ok'])
            upgraded=installer.install(ROOT,home,True);self.assertTrue(Path(upgraded['backup']).is_dir())
            result=installer.uninstall(home);self.assertTrue(result['ok']);self.assertFalse(installer.status(home)['installed'])
    def test_refuses_unmanaged_existing_plugin(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);target=home/'plugins/art-cli';target.mkdir(parents=True);(target/'mine.txt').write_text('unchanged')
            with self.assertRaises(ValueError):installer.install(ROOT,home,True)
            self.assertEqual((target/'mine.txt').read_text(),'unchanged')
    def test_refuses_unmanaged_launcher_before_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);bin=home/'bin';bin.mkdir();file=bin/('art.cmd' if os.name=='nt' else 'art');file.write_text('mine')
            with self.assertRaises(ValueError):installer.install(ROOT,home)
            self.assertFalse((home/'plugins/art-cli').exists());self.assertEqual(file.read_text(),'mine')
    def test_status_detects_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);installer.install(ROOT,home);(home/'plugins/art-cli/art.py').write_text('changed')
            report=installer.status(home);self.assertFalse(report['ok']);self.assertIn('art.py',report['changed_files'])
if __name__=='__main__':unittest.main()
