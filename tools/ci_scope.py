#!/usr/bin/env python3
"""Decide how wide the CI matrix runs for one push or pull request.

Docs-only changes (Markdown, PDF, PNG) run the Linux suite only. Changes that
touch only CCGuard (the Windows monitor panel, its packaging and tests) plus
docs run Linux and Windows: CCGuard is Windows-only and none of its tests need
macOS. Anything else, or a range that cannot be read, runs the full
three-platform matrix, so the Skill's macOS scripts keep their macOS run.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

DOC_SUFFIXES = (".md", ".pdf", ".png")
FULL = {"scope": "full", "os": ["ubuntu-latest", "macos-latest", "windows-latest"]}
WINDOWS = {"scope": "windows", "os": ["ubuntu-latest", "windows-latest"]}
DOCS = {"scope": "docs", "os": ["ubuntu-latest"]}
# CCGuard-only files: exact paths and folder prefixes. Shared code (package_skill.py, other Skill
# scripts, assets or tests) is deliberately absent and keeps the full matrix.
_SCRIPTS = "skills/claude-guardian/scripts/"
CCGUARD_FILES = {
    "CCGuard.pyw", "CCGuard.cmd", "requirements-build.txt", "requirements-desktop.txt", ".gitignore",
    "tools/build_windows.py", ".github/workflows/windows-installer.yml",
    *(_SCRIPTS + name for name in ("monitor.py", "monitor_gui.py", "monitor_webview.py", "monitor_history.py",
                                   "monitor_guide.py", "ip_score.py", "app_update.py", "version.py")),
    *("tests/" + name for name in ("test_monitor.py", "test_monitor_gui.py", "test_monitor_webview.py",
                                   "test_monitor_history.py", "test_ip_score.py", "test_app_update.py",
                                   "test_windows_build.py", "test_launcher.py", "monitor-panel.cjs",
                                   "monitor-interaction.cjs")),
}
CCGUARD_PREFIXES = ("skills/claude-guardian/assets/monitor/", "packaging/")


def is_doc(name: str) -> bool:
    return not name.startswith(".github/") and name.lower().endswith(DOC_SUFFIXES)


def is_ccguard(name: str) -> bool:
    return name in CCGUARD_FILES or name.startswith(CCGUARD_PREFIXES)


def classify(files: list[str]) -> dict:
    if not files:
        return FULL
    if all(is_doc(name) for name in files):
        return DOCS
    if all(is_doc(name) or is_ccguard(name) for name in files):
        return WINDOWS
    return FULL


def changed_files(base: str, head: str) -> list[str] | None:
    if not base or set(base) == {"0"}:
        return None
    result = subprocess.run(["git", "diff", "--name-only", base, head],
                            capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    args = parser.parse_args(argv)
    files = changed_files(args.base, args.head)
    result = classify(files or [])
    print(f"scope={result['scope']} files={'unknown' if files is None else len(files)}", file=sys.stderr)
    out = os.environ.get("GITHUB_OUTPUT")
    lines = f"scope={result['scope']}\nos={json.dumps(result['os'])}\n"
    if out:
        with open(out, "a", encoding="utf-8") as handle:
            handle.write(lines)
    else:
        sys.stdout.write(lines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
