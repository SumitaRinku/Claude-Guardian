"""Exercise the double-click launcher's path resolution; never opens a window."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


launcher = load('ccguard_launcher', ROOT / 'CCGuard.pyw')


class Launcher(unittest.TestCase):
    def test_repository_layout_resolves(self):
        self.assertEqual(launcher.locate_scripts(), ROOT / 'skills' / 'claude-guardian' / 'scripts')

    def test_release_package_layout_resolves(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / 'scripts').mkdir()
            (base / 'scripts' / 'monitor.py').write_text('', encoding='utf-8')
            self.assertEqual(launcher.locate_scripts(base), base / 'scripts')

    def test_missing_layout_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertIsNone(launcher.locate_scripts(Path(folder)))

    def test_cmd_launcher_prefers_pythonw_and_calls_the_pyw(self):
        body = (ROOT / 'CCGuard.cmd').read_text(encoding='utf-8')
        self.assertIn('pythonw.exe', body)
        self.assertIn('pyw.exe', body)
        self.assertIn('CCGuard.pyw', body)
        self.assertIn('start ""', body)
        self.assertIn(b'\r\n', (ROOT / 'CCGuard.cmd').read_bytes())


if __name__ == '__main__':
    unittest.main()
