"""Exe / installer build: the pieces that must agree with the app, checked without building."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/claude-guardian/scripts'
sys.path.insert(0, str(SCRIPTS))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load('build_windows', ROOT / 'tools/build_windows.py')
app = load('ccguard_app', ROOT / 'packaging/ccguard_app.py')
import monitor  # noqa: E402
import monitor_gui  # noqa: E402

ISS = (ROOT / 'packaging/ccguard.iss').read_text(encoding='utf-8')
SPEC = (ROOT / 'packaging/ccguard.spec').read_text(encoding='utf-8')
WORKFLOW = (ROOT / '.github/workflows/windows-installer.yml').read_text(encoding='utf-8')


class Version(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(build.parse_version('v0.5.0'), ('0.5.0', (0, 5, 0, 0)))
        self.assertEqual(build.parse_version('12.0.3'), ('12.0.3', (12, 0, 3, 0)))
        for bad in ('', '0.5', '0.5.0-rc1', 'latest', None):
            with self.assertRaises(build.BuildError):
                build.parse_version(bad)

    def test_version_resource_names_the_product(self):
        text = build.version_info('0.5.0', (0, 5, 0, 0))
        self.assertIn('filevers=(0, 5, 0, 0)', text)
        for value in ("'ProductName', 'CCGuard'", "'ProductVersion', '0.5.0'", "'OriginalFilename', 'CCGuard.exe'"):
            self.assertIn(value, text)


class SingleVersion(unittest.TestCase):
    def test_build_reads_version_py(self):
        import version
        self.assertEqual(build.source_version(), version.__version__)
        self.assertEqual(build.resolve_version()[0], version.__version__)
        self.assertEqual(build.resolve_version('v' + version.__version__)[0], version.__version__)

    def test_release_tag_must_match_version_py(self):
        with self.assertRaises(build.BuildError):
            build.resolve_version('v99.0.0')

    def test_release_workflow_passes_the_tag(self):
        self.assertIn("$tag = @('--version', '${{ github.event.release.tag_name }}')", WORKFLOW)
        self.assertNotIn('inputs.version', WORKFLOW)

    def test_self_test_checks_version_and_update_log(self):
        source = (ROOT / 'packaging/ccguard_app.py').read_text(encoding='utf-8')
        self.assertIn("'release notes match version'", source)
        self.assertIn("'release-notes.json'", source)
        for name in ("'app_update'", "'version'"):
            self.assertIn(name, SPEC)


class BundledFont(unittest.TestCase):
    def test_pinned_to_a_google_fonts_commit_with_hashes(self):
        self.assertRegex(build.FONT_COMMIT, r'^[0-9a-f]{40}$')
        self.assertTrue(build.FONT_BASE.startswith('https://raw.githubusercontent.com/google/fonts/' + build.FONT_COMMIT))
        names = {bundled for _, bundled, _, _ in build.FONT_FILES}
        self.assertEqual(names, {'NotoSansSC-VF.ttf', 'OFL.txt'})
        for _, _, size, digest in build.FONT_FILES:
            self.assertGreater(size, 0)
            self.assertRegex(digest, r'^[0-9a-f]{64}$')

    def test_fetch_verifies_size_and_hash(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            good = {url: data for url, data in ((build.FONT_BASE + up, b'x' * size) for up, _, size, _ in build.FONT_FILES)}
            files = tuple((up, name, size, hashlib.sha256(b'x' * size).hexdigest()) for up, name, size, _ in build.FONT_FILES)
            with patch.object(build, 'FONT_DIR', Path(folder) / 'fonts'), patch.object(build, 'FONT_FILES', files):
                build.fetch_fonts(get=good.__getitem__)
                self.assertTrue((Path(folder) / 'fonts' / 'NotoSansSC-VF.ttf').is_file())
                build.fetch_fonts(get=lambda url: self.fail('cached file must not be fetched again'))
                (Path(folder) / 'fonts' / 'OFL.txt').write_bytes(b'tampered')
                with self.assertRaises(build.BuildError):
                    build.fetch_fonts(get=lambda url: b'tampered')

    def test_spec_bundles_the_font_and_refuses_a_build_without_it(self):
        self.assertIn("(str(FONT_DIR), 'claude-guardian/assets/monitor/fonts')", SPEC)
        self.assertIn("raise SystemExit", SPEC)
        source = (ROOT / 'packaging/ccguard_app.py').read_text(encoding='utf-8')
        self.assertIn("'fonts/NotoSansSC-VF.ttf', 'fonts/OFL.txt'", source)

    def test_page_prefers_the_bundled_face(self):
        css = (ROOT / 'skills/claude-guardian/assets/monitor/panel.css').read_text(encoding='utf-8')
        self.assertIn('src: url("fonts/NotoSansSC-VF.ttf")', css)
        stack = css.split('--font-ui:', 1)[1].split(';', 1)[0]
        self.assertTrue(stack.strip().startswith('"CCGuard Sans"'))

    def test_font_is_never_committed(self):
        ignored = (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
        self.assertIn('/skills/claude-guardian/assets/monitor/fonts/', ignored)


class InstallerAgreesWithTheApp(unittest.TestCase):
    def test_per_user_install_without_admin(self):
        self.assertIn('PrivilegesRequired=lowest', ISS)
        self.assertIn(r'DefaultDirName={localappdata}\Programs\CCGuard', ISS)

    def test_running_panel_is_closed_before_files_change(self):
        # Inno checks the session namespace, which is where Local\ mutexes live.
        self.assertTrue(monitor_gui.INSTANCE_MUTEX_NAME.startswith('Local\\'))
        self.assertIn('AppMutex=' + monitor_gui.INSTANCE_MUTEX_NAME.split('\\', 1)[1], ISS)

    def test_start_menu_shortcut_carries_the_notification_identity(self):
        self.assertIn(r'Name: "{userprograms}\%s"' % monitor.APP_NAME, ISS)
        self.assertIn('AppUserModelID: "%s"' % monitor.APP_ID, ISS)

    def test_uninstall_removes_the_autostart_entry(self):
        self.assertIn(r'Name: "{userstartup}\%s.lnk"' % monitor.APP_NAME, ISS)

    def test_chinese_wizard_ships_with_the_repo(self):
        # Regression: the runner's Inno Setup has no ChineseSimplified.isl and the build failed,
        # so the translation is kept in the repository and referenced relative to the script.
        self.assertIn(r'Name: "chinesesimplified"; MessagesFile: "languages\ChineseSimplified.isl"', ISS)
        self.assertIn('Name: "english"; MessagesFile: "compiler:Default.isl"', ISS)
        self.assertIn('ShowLanguageDialog=auto', ISS)
        isl = ROOT / 'packaging/languages/ChineseSimplified.isl'
        data = isl.read_bytes()
        import hashlib
        blob = hashlib.sha1((b'blob %d\x00' % len(data)) + data).hexdigest()
        self.assertEqual(blob, 'd6a11c4490de07dad443ade668289fc954dfa1ed')  # upstream is-6_7_4
        text = data.decode('utf-8')
        self.assertIn('LanguageID=$0804', text)
        self.assertIn('Maintained by Zhenghan Yang', text)

    def test_translation_is_not_line_ending_normalised(self):
        attributes = (ROOT / '.gitattributes').read_text(encoding='utf-8')
        self.assertIn('packaging/languages/*.isl -text', attributes)


class Bundle(unittest.TestCase):
    def test_spec_bundles_assets_where_monitor_looks_when_frozen(self):
        self.assertIn("'claude-guardian/assets/monitor'", SPEC)
        self.assertIn('console=False', SPEC)

    def test_every_lazily_imported_module_is_named(self):
        for name in ('monitor_webview', 'monitor_gui', 'monitor_history', 'monitor_guide', 'ip_score',
                     'webview.platforms.winforms'):
            self.assertIn("'%s'" % name, SPEC)

    def test_frozen_root_and_shortcut_target(self):
        argv = monitor.launcher_argv(Path('c.json'), 0, hidden=True, frozen=True)
        self.assertEqual(argv[1:3], ['gui', '--config'])
        self.assertIn('--start-hidden', argv)
        self.assertNotIn(str(SCRIPTS / 'monitor.py'), argv)
        self.assertEqual(monitor.launch_target(frozen=True)[0], Path(sys.executable))
        script_argv = monitor.launcher_argv(Path('c.json'), 0, frozen=False)
        self.assertEqual(Path(script_argv[1]).name, 'monitor.py')

    def test_monitor_resolves_frozen_root_from_the_bundle(self):
        source = (SCRIPTS / 'monitor.py').read_text(encoding='utf-8')
        self.assertIn("Path(getattr(sys, '_MEIPASS', '.')) / 'claude-guardian'", source)


class Entry(unittest.TestCase):
    def test_arguments_go_to_the_monitor_cli(self):
        with patch.object(monitor, 'main', return_value=0) as called:
            self.assertEqual(app.main(['gui', '--config', 'x.json', '--tray']), 0)
        called.assert_called_once_with(['gui', '--config', 'x.json', '--tray'])

    def test_cli_errors_are_shown_when_there_is_no_console(self):
        shown = []

        def failing(argv):
            sys.stderr.write('请用 --config 指定监测配置。\n')
            return 2
        with patch.object(sys, 'stderr', None), patch.object(sys, 'stdout', None), \
                patch.object(monitor, 'main', side_effect=failing), patch.object(app, 'show_error', shown.append):
            self.assertEqual(app.main(['check']), 2)
        self.assertEqual(shown, ['请用 --config 指定监测配置。'])

    def test_unexpected_failure_is_shown_not_raised(self):
        shown = []
        with patch.object(monitor, 'quickstart_config', side_effect=RuntimeError('boom')), \
                patch.object(app, 'show_error', shown.append):
            self.assertEqual(app.main([]), 1)
        self.assertEqual(shown, ['CCGuard 启动失败：boom'])

    def test_self_test_reports_each_item(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / 'r.json'
            app.self_test(report)
            data = json.loads(report.read_text(encoding='utf-8'))
        self.assertFalse(data['frozen'])
        for key in ('import monitor_webview', 'asset panel.html', 'asset tray.ps1'):
            self.assertIs(data['checks'][key], True, key)


class Workflow(unittest.TestCase):
    def test_builds_on_windows_verifies_and_attaches_to_releases(self):
        self.assertIn('runs-on: windows-latest', WORKFLOW)
        self.assertIn('types: [published]', WORKFLOW)
        self.assertIn('--installer --verify-installer', WORKFLOW)
        self.assertIn("if: github.event_name == 'release'", WORKFLOW)
        self.assertIn('gh release upload', WORKFLOW)
        self.assertIn('pip install -r requirements-build.txt', WORKFLOW)

    def test_build_tools_are_pinned(self):
        lines = [line for line in (ROOT / 'requirements-build.txt').read_text(encoding='utf-8').splitlines()
                 if line and not line.startswith('#')]
        self.assertTrue(lines)
        self.assertTrue(all('==' in line for line in lines), lines)

    def test_build_output_is_ignored(self):
        ignored = (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
        self.assertIn('/build/', ignored)
        self.assertIn('/dist/', ignored)


if __name__ == '__main__':
    unittest.main()
