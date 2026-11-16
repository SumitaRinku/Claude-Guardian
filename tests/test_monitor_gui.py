"""Exercise the native panel's pure logic and assets; never opens a window."""
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/claude-guardian/scripts'
ASSETS = ROOT / 'skills/claude-guardian/assets/monitor'
sys.path.insert(0, str(SCRIPTS))

gui = importlib.import_module('monitor_gui')
engine = sys.modules['monitor']


def config(tmp):
    return {
        'version': 1,
        'target': engine.platform.node(),
        'proxy': {'process_names': ['FlClashCore'], 'tun_adapter': 'FlClash',
                  'runtime_config': str(tmp / 'config.yaml')},
        'firewall': {'expect_default_block': True, 'allow_rule_prefix': 'guardian-', 'min_allow_rules': 1},
        'network': {'expect_dns_servers': ['198.18.0.2'], 'expect_ipv6_disabled': True},
        'alerts': {'cooldown_seconds': 120, 'notify_states': ['fail', 'degraded'], 'interval_seconds': 5},
    }


class Rows(unittest.TestCase):
    def test_build_rows_keeps_order_labels_and_codes(self):
        state = {'checks': [{'id': 'proxy_core', 'state': 'ok', 'code': 'PROXY_CORE_RUNNING'},
                            {'id': 'strict_route', 'state': 'degraded', 'code': 'STRICT_ROUTE_OFF'},
                            {'id': 'custom', 'state': 'unknown'}]}
        rows = gui.build_rows(state)
        self.assertEqual([row['label'] for row in rows], ['代理核心', '严格路由', 'custom'])
        self.assertEqual(rows[1]['state'], 'degraded')
        self.assertEqual(rows[2]['code'], '—')

    def test_build_rows_tolerates_missing_state(self):
        self.assertEqual(gui.build_rows(None), [])


class Settings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_applies_valid_values(self):
        gui.apply_settings(self.cfg, '10', '30', {'fail': True, 'degraded': False, 'unknown': True}, True)
        self.assertEqual(self.cfg['alerts']['interval_seconds'], 10)
        self.assertEqual(self.cfg['alerts']['cooldown_seconds'], 30)
        self.assertEqual(self.cfg['alerts']['notify_states'], ['fail', 'unknown'])
        self.assertTrue(self.cfg['alerts']['paused'])

    def test_rejects_out_of_range_and_bad_types(self):
        for values in [('1', '30'), ('4000', '30'), ('10', '-1'), ('abc', '30'), ('10', 'x')]:
            with self.assertRaises(engine.MonitorError):
                gui.validate_settings(values[0], values[1], {'fail': True})

    def test_rejects_unknown_notify_state(self):
        with self.assertRaises(engine.MonitorError):
            gui.validate_settings(5, 0, {'ok': True})


class SaveConfig(unittest.TestCase):
    """Regression: saving from the panel used to write a config that load_config then rejected."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cfg = config(self.dir)
        self.path = self.dir / 'monitor.json'
        self.path.write_text(json.dumps(self.cfg), encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def test_saved_settings_reload_including_paused(self):
        for paused in (True, False):
            gui.apply_settings(self.cfg, '15', '60', {'fail': True, 'unknown': True}, paused)
            gui.save_config(self.path, self.cfg)
            loaded = engine.load_config(self.path)
            self.assertEqual(loaded['alerts']['interval_seconds'], 15)
            self.assertIs(loaded['alerts']['paused'], paused)
        self.assertEqual([p.name for p in self.dir.iterdir() if p.suffix == '.tmp'], [])

    def test_invalid_config_is_never_written(self):
        original = self.path.read_bytes()
        self.cfg['alerts']['interval_seconds'] = 1
        with self.assertRaises(engine.MonitorError):
            gui.save_config(self.path, self.cfg)
        self.assertEqual(self.path.read_bytes(), original)

    def test_load_rejects_non_boolean_paused(self):
        self.cfg['alerts']['paused'] = 'yes'
        self.path.write_text(json.dumps(self.cfg), encoding='utf-8')
        with self.assertRaises(engine.MonitorError):
            engine.load_config(self.path)


class CloseChoices(unittest.TestCase):
    def test_hide_is_offered_only_with_a_live_tray(self):
        self.assertIn('hide', gui.close_choices(True))
        self.assertNotIn('hide', gui.close_choices(False))
        self.assertIn('exit', gui.close_choices(False))
        self.assertIn(None, gui.close_choices(False))


class PanelSource(unittest.TestCase):
    def test_card_does_not_shadow_tkinter_update(self):
        source = (SCRIPTS / 'monitor_gui.py').read_text(encoding='utf-8')
        self.assertNotIn('def update(self', source)

    def test_ui_thread_never_runs_a_blocking_collection(self):
        source = (SCRIPTS / 'monitor_gui.py').read_text(encoding='utf-8')
        self.assertNotIn('store.refresh()', source)


class Events(unittest.TestCase):
    def test_event_text_covers_problem_and_recovery(self):
        self.assertIn('恢复正常', gui.event_text({'id': 'tun_adapter', 'from': 'fail', 'to': 'ok'}))
        self.assertIn('失效', gui.event_text({'id': 'tun_adapter', 'from': 'ok', 'to': 'fail'}))


class Buffer(unittest.TestCase):
    def test_buffer_is_bounded_and_ordered(self):
        log = gui.LogBuffer(limit=3)
        for index in range(5):
            log.add('状态', 'row %d' % index)
        rows = log.snapshot()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1][2], 'row 4')

    def test_total_keeps_growing_after_buffer_is_full(self):
        # Regression: the panel compared len(snapshot) and stopped refreshing at the limit.
        log = gui.LogBuffer(limit=2)
        seen = []
        for index in range(4):
            log.add('状态', str(index))
            seen.append(log.total)
        self.assertEqual(seen, [1, 2, 3, 4])
        self.assertEqual(len(log.snapshot()), 2)


def fake_font(path, family):
    """Smallest sfnt with only a 'name' table holding a Windows-English family name (ID 1)."""
    import struct
    text = family.encode('utf-16-be')
    name = struct.pack('>HHH', 0, 1, 6 + 12) + struct.pack('>HHHHHH', 3, 1, 0x409, 1, len(text), 0) + text
    header = struct.pack('>IHHHH', 0x00010000, 1, 16, 0, 0)
    directory = struct.pack('>4sIII', b'name', 0, 12 + 16, len(name))
    Path(path).write_bytes(header + directory + name)
    return Path(path)


REPO_FONTS = ROOT / 'fonts'


class Fonts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fallbacks_without_user_fonts(self):
        families = gui.font_families([])
        self.assertEqual(families, {'ui': 'Microsoft YaHei UI', 'serif': 'Segoe UI Semibold',
                                    'mono': 'Cascadia Mono', 'log': 'Microsoft YaHei UI'})

    def test_installed_fonts_are_preferred_over_missing_fallbacks(self):
        families = gui.font_families([], {'Microsoft YaHei UI', 'Segoe UI', 'Consolas'})
        self.assertEqual(families['ui'], 'Microsoft YaHei UI')
        self.assertEqual(families['serif'], 'Microsoft YaHei UI')
        self.assertEqual(families['mono'], 'Consolas')
        self.assertEqual(families['log'], families['ui'])

    def test_log_font_is_cjk_capable_ui_font(self):
        self.assertEqual(gui.font_families([])['log'], gui.font_families([])['ui'])

    def test_family_is_read_from_the_font_not_the_file_name(self):
        path = fake_font(self.dir / 'whatever.otf', 'Anthropic Sans Text')
        self.assertEqual(gui.font_family(path), 'Anthropic Sans Text')
        self.assertIsNone(gui.font_family(self.dir / 'missing.ttf'))
        (self.dir / 'broken.ttf').write_bytes(b'not a font')
        self.assertIsNone(gui.font_family(self.dir / 'broken.ttf'))

    def test_static_sans_text_is_preferred_over_web_text(self):
        files = [fake_font(self.dir / 'a.ttf', 'Anthropic Sans Web Text'),
                 fake_font(self.dir / 'b.otf', 'Anthropic Sans Text'),
                 fake_font(self.dir / 'c.ttf', 'Anthropic Serif Web Text'),
                 fake_font(self.dir / 'd.ttf', 'Anthropic Mono Variable')]
        self.assertEqual(gui.font_families(files), {'ui': 'Anthropic Sans Text',
                                                    'serif': 'Anthropic Serif Web Text',
                                                    'mono': 'Anthropic Mono Variable',
                                                    'log': 'Anthropic Sans Text'})
        self.assertEqual(gui.font_families(files[:1])['ui'], 'Anthropic Sans Web Text')

    def test_discovery_includes_subfolders_and_both_formats(self):
        sub = self.dir / 'Anthropic Sans'
        sub.mkdir()
        fake_font(self.dir / 'top.ttf', 'X')
        fake_font(sub / 'nested.OTF', 'Y')
        (sub / 'readme.txt').write_text('x', encoding='utf-8')
        names = {p.name for p in gui.font_files([self.dir, self.dir / 'absent'])}
        self.assertEqual(names, {'top.ttf', 'nested.OTF'})

    @unittest.skipUnless((REPO_FONTS / 'Anthropic Sans').is_dir(), 'user-supplied fonts are not in the repository')
    def test_user_supplied_fonts_resolve_when_present(self):
        families = gui.font_families(gui.font_files())
        self.assertEqual(families['ui'], 'Anthropic Sans Text')

    def test_rounded_points_returns_closed_outline(self):
        points = gui.rounded_points(0, 0, 100, 40, 10)
        self.assertEqual(len(points), 24)
        self.assertEqual(points[:2], [10, 0])


class Logo(unittest.TestCase):
    def test_header_logos_exist_for_every_state(self):
        for state in engine.STATES:
            data = (ASSETS / ('logo-' + state + '.png')).read_bytes()
            self.assertEqual(data[:8], bytes.fromhex('89504e470d0a1a0a'), state)
            self.assertEqual(int.from_bytes(data[16:20], 'big'), 128, state)

    def test_logo_shrinks_to_about_44px_and_scales_with_dpi(self):
        self.assertEqual(gui.logo_subsample(128, 1.0), 3)
        self.assertEqual(gui.logo_subsample(128, 1.5), 2)
        self.assertEqual(gui.logo_subsample(128, 3.0), 1)

    def test_window_icon_is_set_on_the_window_not_only_the_class(self):
        # Regression: iconbitmap could not read the PNG 256 frame, and iconphoto(True) alone only
        # replaced Tk's class icon, so the title bar kept the generic window icon.
        source = (SCRIPTS / 'monitor_gui.py').read_text(encoding='utf-8')
        self.assertIn('root.iconphoto(False,', source)
        self.assertNotIn('.iconbitmap(', source)
        self.assertIn('SetCurrentProcessExplicitAppUserModelID', source)


class UiWiring(unittest.TestCase):
    def test_ttk_controls_autostart_and_hidden_start_are_wired(self):
        source = (SCRIPTS / 'monitor_gui.py').read_text(encoding='utf-8')
        for text in ('ttk.Spinbox', 'ttk.Checkbutton', 'ttk.Scrollbar',
                     'engine.enable_autostart(config_path)', 'engine.disable_autostart()',
                     'start_hidden', "text='开机自启'", 'if start_hidden and tray_alive():'):
            self.assertIn(text, source)
        self.assertIn("families['log']", source)


class Assets(unittest.TestCase):
    def test_state_icons_exist_with_multiple_frames(self):
        for state in engine.STATES:
            path = ASSETS / ('icon-' + state + '.ico')
            self.assertTrue(path.is_file(), state)
            data = path.read_bytes()
            self.assertEqual(data[:4], b'\x00\x00\x01\x00')
            count = int.from_bytes(data[4:6], 'little')
            self.assertGreaterEqual(count, 4, state)

    def test_small_frames_are_dib_and_only_256_is_png(self):
        # Regression: PNG-compressed small frames decoded as noise in System.Drawing.Icon
        # (used by the tray), and an unrolled byte array once produced 125-byte icons.
        for state in engine.STATES:
            data = (ASSETS / ('icon-' + state + '.ico')).read_bytes()
            count = int.from_bytes(data[4:6], 'little')
            sizes = []
            for index in range(count):
                entry = data[6 + 16 * index:22 + 16 * index]
                size = entry[0] or 256
                length = int.from_bytes(entry[8:12], 'little')
                offset = int.from_bytes(entry[12:16], 'little')
                frame = data[offset:offset + length]
                self.assertEqual(len(frame), length, state)
                if size == 256:
                    self.assertEqual(frame[:8], bytes.fromhex('89504e470d0a1a0a'), state)
                else:
                    self.assertEqual(int.from_bytes(frame[:4], 'little'), 40, (state, size))
                    self.assertEqual(int.from_bytes(frame[4:8], 'little'), size)
                    self.assertEqual(int.from_bytes(frame[8:12], 'little'), size * 2)
                    self.assertEqual(int.from_bytes(frame[14:16], 'little'), 32)
                sizes.append(size)
            self.assertEqual(sizes, [16, 20, 24, 32, 48, 64, 256], state)

    def test_panel_icon_is_the_ok_state(self):
        self.assertTrue(engine.ICON.is_file())
        self.assertEqual(engine.ICON.name, 'icon-ok.ico')


if __name__ == '__main__':
    unittest.main()
