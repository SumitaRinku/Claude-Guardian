import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ci_scope", ROOT / "tools" / "ci_scope.py")
ci_scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci_scope)


class CiScopeTests(unittest.TestCase):
    def test_docs_only_runs_linux(self):
        result = ci_scope.classify(["CHANGELOG.md", "skills/claude-guardian/references/account-onboarding.md",
                                    "skills/claude-guardian/sources/S03-claude-experience.pdf"])
        self.assertEqual(result["scope"], "docs")
        self.assertEqual(result["os"], ["ubuntu-latest"])

    def test_any_code_test_or_data_file_runs_full_matrix(self):
        for name in ("tools/ci_scope.py", "tests/test_guides.py", "skills/claude-guardian/sources/manifest.json",
                     "skills/claude-guardian/assets/webrtc-probe.html", "skills/claude-guardian/assets/vps-firewall/vps-guard.sh"):
            self.assertEqual(ci_scope.classify(["README.md", name])["scope"], "full", name)

    def test_ccguard_only_changes_skip_macos(self):
        for files in (["skills/claude-guardian/scripts/monitor_webview.py", "CHANGELOG.md"],
                      ["skills/claude-guardian/assets/monitor/panel.css", "tests/test_monitor_gui.py", ".gitignore"],
                      ["packaging/ccguard.iss", "tools/build_windows.py", ".github/workflows/windows-installer.yml"],
                      ["skills/claude-guardian/scripts/version.py", "skills/claude-guardian/assets/monitor/release-notes.json",
                       "tests/monitor-panel.cjs", "CCGuard.pyw", "requirements-build.txt"]):
            result = ci_scope.classify(files)
            self.assertEqual(result["scope"], "windows", files)
            self.assertEqual(result["os"], ["ubuntu-latest", "windows-latest"])

    def test_skill_or_shared_code_mixed_in_keeps_macos(self):
        for extra in ("skills/claude-guardian/scripts/native_cleanup_mac.py", "tests/test_mac_pf_killswitch.py",
                      "skills/claude-guardian/assets/mac-killswitch/guardian-pf-killswitch.sh", "tools/package_skill.py",
                      "tools/ci_scope.py", ".github/workflows/tests.yml", "skills/claude-guardian/scripts/guardian.py",
                      "skills/claude-guardian/assets/killswitch/switch.js", "tests/test_guides.py", ".gitattributes"):
            result = ci_scope.classify(["skills/claude-guardian/scripts/monitor.py", extra])
            self.assertEqual(result["scope"], "full", extra)
            self.assertIn("macos-latest", result["os"])

    def test_every_mac_specific_file_keeps_macos(self):
        tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
        mac = [name for name in tracked if "mac" in name.lower() and not ci_scope.is_doc(name)]
        self.assertTrue(mac)
        for name in mac:
            self.assertEqual(ci_scope.classify([name])["scope"], "full", name)

    def test_workflow_markdown_still_runs_full_matrix(self):
        self.assertEqual(ci_scope.classify([".github/ISSUE_TEMPLATE/x.md"])["scope"], "full")

    def test_unreadable_range_runs_full_matrix(self):
        self.assertEqual(ci_scope.classify([])["scope"], "full")
        self.assertIsNone(ci_scope.changed_files("0" * 40, "HEAD"))
        self.assertIsNone(ci_scope.changed_files("", "HEAD"))

    def test_cli_reads_git_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = lambda *a: subprocess.run(["git", *a], cwd=tmp, check=True, capture_output=True, text=True)
            run("init", "-q")
            run("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "a")
            Path(tmp, "a.md").write_text("x", encoding="utf-8")
            run("add", "a.md")
            run("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "b")
            out = subprocess.run([sys.executable, str(ROOT / "tools" / "ci_scope.py"), "--base", "HEAD~1", "--head", "HEAD"],
                                 cwd=tmp, capture_output=True, text=True, check=True,
                                 env={k: v for k, v in __import__("os").environ.items() if k != "GITHUB_OUTPUT"})
            self.assertIn("scope=docs", out.stdout)
            Path(tmp, "b.py").write_text("x", encoding="utf-8")
            run("add", "b.py")
            run("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "c")
            out = subprocess.run([sys.executable, str(ROOT / "tools" / "ci_scope.py"), "--base", "HEAD~1", "--head", "HEAD"],
                                 cwd=tmp, capture_output=True, text=True, check=True,
                                 env={k: v for k, v in __import__("os").environ.items() if k != "GITHUB_OUTPUT"})
            self.assertIn("scope=full", out.stdout)

    def test_workflow_uses_the_scope(self):
        wf = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
        self.assertIn("tools/ci_scope.py", wf)
        self.assertIn("fromJSON(needs.scope.outputs.os)", wf)
        self.assertIn("needs.scope.outputs.scope == 'full'", wf)


if __name__ == "__main__":
    unittest.main()
