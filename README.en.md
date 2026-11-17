<div align="center">

<img src="skills/claude-guardian/assets/monitor/logo-ok.png" width="96" height="96" alt="CCGuard shield">

# CCGuard

**A read-only Windows status panel for your proxy, TUN, route, firewall, DNS and IPv6.**

Monitoring stays offline · Exit score on demand · No system changes · No admin rights

<p>
  <img alt="Windows 10/11" src="https://img.shields.io/badge/Windows-10%2F11-0078D4?style=flat-square">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="GPL-3.0-only" src="https://img.shields.io/badge/License-GPL--3.0--only-2E7D32?style=flat-square">
  <a href="https://github.com/SumitaRinku/CCguard/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/SumitaRinku/CCguard?style=flat-square"></a>
</p>

**English** · [中文](README.md)

[Quick start](#quick-start) · [Checks](#checks) · [Supported clients](#supported-proxy-clients) · [Configuration](#configuration) · [Safety boundaries](#safety-boundaries) · [Docs](#documentation) · [Development](#development-and-verification)

</div>

---

## What CCGuard is

CCGuard is the Windows read-only status panel maintained in this repository on top of [Claude-Guardian](https://github.com/DUNHKpcc/Claude-Guardian). It is for a machine where the proxy, TUN and firewall are already deployed, and answers one question continuously: **is the protection still in place?**

It splits the state into 10 checks and shows them in green / orange / red / grey in a window, a tray icon and an optional local web page; it raises a system notification when a key check fails. The monitor does not change the firewall, restart the proxy or edit the configuration, and the 10 checks make no outbound request, so it is safe to leave running; when you want to know how clean the exit IP is, run the exit score by hand.

> A passing monitor only means the local state matches the expected configuration. It does not certify egress IP, DNS, accounts or platform acceptance, and it does not guarantee avoiding bans.

> The Chinese [README.md](README.md) is the source text; where the two differ, the Chinese version wins.

## What it does

| Capability | What it does |
| --- | --- |
| **10 live checks** | Proxy core, TUN, default route, firewall, allow rules, core IPv6 / strict route / DNS hijack, physical-adapter DNS / IPv6 |
| **Double-click start** | Extract the release package and double-click `CCGuard.pyw` (or `CCGuard.cmd`); the first run writes a config and opens the panel, and a second double-click does not open another window |
| **One-command start** | `quickstart` detects the host, client and TUN, writes a config and opens the panel; an existing config is never overwritten |
| **State-coloured shield** | Green ✓ ok, orange ! degraded, red ✕ fail, grey — unknown; window, tray and page title stay in sync |
| **New UI** | WebView desktop panel (pywebview + Edge WebView2): status banner, sidebar problem count, coloured log, follows system dark mode, window sized to its content; falls back to the tkinter panel when pywebview is missing |
| **State history** | 24-hour / 7-day timeline per check, with unmonitored time shown separately; stored in `history.jsonl` next to the config, check ids and states only, kept for 7 days |
| **Fix guidance** | Click any check card to see what it checks, the steps for the current result, its last 24 hours and the result code |
| **Detection log** | Every check records which system query it read, what it saw and why it reached its state; listed under "检测过程" in the card detail, without IP addresses or file paths. See [how checks work](skills/claude-guardian/references/monitor.md#principles) |
| **Exit score** | On the "出口" page, on demand: ask Cloudflare for the exit IP over the current network, then fetch its trust score, IP type, location, network and risk flags from [ip.net.coffee](https://ip.net.coffee/claude/), with every request listed; open the full report in your browser with one click. Never contacts Claude; see [exit score](skills/claude-guardian/references/monitor.md#exit-score) |
| **Window + tray + web** | WebView panel (default) / tkinter panel (fallback), tray notifications, local `127.0.0.1` web page as an alternative |
| **System notifications** | Alerts on state transitions with cooldown and recovery notices; can be paused |
| **Optional autostart** | A per-user Startup shortcut opens the panel hidden in the tray at login; off by default |
| **Client presets** | FlClash, Clash Verge Rev, Clash Nyanpasu, Clash for Windows, Mihomo / Clash.Meta, sing-box, Hiddify, v2rayN, NekoRay / NekoBox |
| **TUN auto-detection** | Matches adapter name / description fragments, so client upgrades usually need no config change |
| **Multiple config formats** | Clash/Mihomo YAML, sing-box JSON (including 1.11+ `address`), Xray JSON; unreadable fields stay `unknown` |
| **Candidate detection** | `monitor.py detect` lists candidate cores, TUN adapters and client presets without a config |

## Safety boundaries

- **Read-only**: no `Set-*`, no firewall/route/proxy changes, no core restart.
- **Monitoring makes no outbound traffic**: the 10 checks only read the local machine; no DNS-leak, latency or WebRTC probes; the web mode only listens on `127.0.0.1`.
- **The exit score goes online only when you click it**: it requests `1.1.1.1/cdn-cgi/trace` and `ip.net.coffee/api/iprisk` only, never claude.ai or anthropic.com; the exit IP is sent to ip.net.coffee and the UI shows only its first two parts. You open the full acceptance page in your own browser.
- **No admin rights**: the monitor runs as a normal user; elevation belongs to other protection scripts.
- **No autostart by default**: no Windows service or scheduled task, and no Startup entry unless you explicitly enable autostart. Enabling creates one CCGuard shortcut in the current user's Startup folder and can be undone at any time.
- **No credentials**: notifications and state contain only state names and check IDs, never IPs, paths, nodes, subscription links or config values.
- **`unknown` is not a pass**: failed queries, missing permissions, unsupported formats or an empty config stay unknown.

## Quick start

### 1. Requirements

- Windows 10 / 11, PowerShell 5.1
- Python 3.10+ (the official installer normally includes tkinter)
- Optional: `python -m pip install -r requirements-desktop.txt` installs pywebview for the WebView UI (Windows 10/11 ship Edge WebView2); without it CCGuard falls back to the tkinter panel
- The proxy client running, with TUN and the firewall already deployed

The monitor uses only the Python standard library; no third-party dependency is needed.

### 2. Get it

**Option A: release package (recommended; double-click and go)**

Recommended: download [`CCGuard-Setup-0.5.1.exe`](https://github.com/SumitaRinku/CCguard/releases/download/v0.5.1/CCGuard-Setup-0.5.1.exe) and run it. It needs neither Python nor administrator rights: it installs for the current user into `%LOCALAPPDATA%\Programs\CCGuard` with Start menu and desktop shortcuts, and can be removed from Settings > Apps. Uninstalling removes the program, its shortcuts and the autostart entry, and keeps your `monitor.json` and `history.jsonl`. The installer is built from source on GitHub Actions and attached to the release only after a silent install, self-test and uninstall pass; `SHA256SUMS-installer-0.5.1.txt` holds its hash. It is not code-signed, so SmartScreen may show "Windows protected your PC" on first run: choose "More info > Run anyway".

Python package: download [`claude-guardian-0.5.1.zip`](https://github.com/SumitaRinku/CCguard/releases/download/v0.5.1/claude-guardian-0.5.1.zip), extract it, and double-click `CCGuard.pyw` or `CCGuard.cmd` inside `claude-guardian\`.

**Option B: clone the repository (latest source)**

```powershell
git clone https://github.com/SumitaRinku/CCguard.git
```

The repository root also has `CCGuard.pyw` / `CCGuard.cmd`; the monitor entry is `skills\claude-guardian\scripts\monitor.py`.

### 3. Double-click start (recommended)

After extracting the release package, enter `claude-guardian\` and double-click:

- `CCGuard.pyw`: no console, recommended; requires `.pyw` to be associated with Python.
- `CCGuard.cmd`: falls back to `python` / `py` when `pythonw` / `pyw` is missing; a console may flash briefly.

The first run writes `%LOCALAPPDATA%\CCGuard\monitor.json` and opens the panel, with no command line needed. Double-clicking again does not open a second window; if it is already running, it tells you to use the tray.

### 4. Command-line start (equivalent)

```bat
:: repository
python skills\claude-guardian\scripts\monitor.py quickstart
```

`quickstart` reads the host name, detects running known clients and TUN adapters, writes `%LOCALAPPDATA%\CCGuard\monitor.json` (an existing config is never overwritten), and opens the panel + tray. The tray keeps alerting after the window closes.

Common options:

```bat
:: pick a client preset
python ...\monitor.py quickstart --client flclash

:: point at the config the client actually loads (absolute path)
python ...\monitor.py quickstart --runtime-config "C:\Users\YOU\AppData\Roaming\com.follow\clash\config.yaml"

:: write the config without opening the panel
python ...\monitor.py quickstart --no-launch

:: also enable autostart (starts hidden in the tray at login)
python ...\monitor.py quickstart --autostart
```

The quick config does not check the allow-rule count or expected DNS servers by default; add them in Settings or the JSON. With an empty `runtime_config`, CCGuard looks for the runtime config in the default places of FlClash and Clash Verge Rev; for other clients, or when nothing is found, the three config checks stay `unknown` and the path has to be filled in.

### 5. Manual configuration (optional)

To fill it in yourself, run `detect` first to see candidate cores and TUN adapters:

```bat
python ...\monitor.py detect
```

Then copy `assets\monitor\config.example.json` to a private directory outside the repository (for example `%USERPROFILE%\.ccguard\monitor.json`) and confirm at least:

- `target`: the exact output of `python -c "import platform; print(platform.node())"`
- `proxy.client`: a preset from the table below
- `proxy.tun_adapter`: keep `auto`; fill the exact adapter name only when detection fails
- `proxy.runtime_config`: the absolute path of the config the client actually loads; when empty, the default places of FlClash and Clash Verge Rev are searched
- `firewall.allow_rule_prefix`, `network.expect_dns_servers`: match your deployment

Never put subscriptions, nodes, passwords or tokens in the file; the schema has no such fields.

### 6. Start, autostart and close

```bat
:: open the panel + tray
python ...\monitor.py gui --config "%LOCALAPPDATA%\CCGuard\monitor.json" --tray

:: enable / disable / check autostart
python ...\monitor.py autostart-enable --config "%LOCALAPPDATA%\CCGuard\monitor.json"
python ...\monitor.py autostart-disable
python ...\monitor.py autostart-status
```

The left sidebar also has an "autostart" checkbox with the same effect. It is off by default; when enabled, login opens the panel hidden in the tray, without a window popping up.

Other entries:

```bat
:: one collection, JSON output (each check carries its source and evidence)
python ...\monitor.py check --config <private>\monitor.json

:: exit score (online: Cloudflare trace + ip.net.coffee, never Claude; no config needed)
python ...\monitor.py ip-score

:: local web page (listens on 127.0.0.1 only, random session token)
python ...\monitor.py serve --config <private>\monitor.json

:: desktop / Start menu entry (does not add autostart)
python ...\monitor.py desktop --config <private>\monitor.json --output <new-dir>

:: name notifications CCGuard (creates one per-user Start menu entry)
python ...\monitor.py register-notifier --config <private>\monitor.json
```

## Supported proxy clients

`proxy.client` selects a built-in preset that fills process names, TUN hints and the config format; `process_names`, `tun_adapter` and `config_format` can still override it.

| `client` | Default process names (sample) | TUN hints (sample) | Config format |
| --- | --- | --- | --- |
| `flclash` | `FlClashCore`, `FlClash` | `flclash`, `meta tunnel` | Clash YAML |
| `clash-verge-rev` | `verge-mihomo`, `clash-verge` | `clash`, `mihomo`, `meta` | Clash YAML |
| `clash-nyanpasu` | `clash-nyanpasu`, `mihomo` | `nyanpasu`, `mihomo` | Clash YAML |
| `clash-for-windows` | `Clash for Windows`, `clash-win64` | `clash` | Clash YAML |
| `mihomo` | `mihomo`, `clash-meta` | `mihomo`, `meta tunnel` | Clash YAML |
| `sing-box` | `sing-box` | `sing-box`, `sing-tun` | sing-box JSON |
| `hiddify` | `Hiddify`, `HiddifyCli`, `sing-box` | `hiddify`, `sing-tun` | sing-box JSON |
| `v2rayn` | `v2rayN`, `xray`, `v2ray` | `v2rayn`, `tun2socks` | Xray JSON |
| `nekoray` | `nekoray`, `nekobox`, `sing-box`, `xray` | `nekoray`, `nekobox` | auto |

- **TUN auto-detection**: `tun_adapter` defaults to `auto` and matches name/description fragments; add a `tun_match` fragment when it cannot find the adapter.
- **Process names**: an omitted `process_names` uses the preset; an explicit list wins; with neither `client` nor `process_names`, any known proxy core counts.
- **Config format**: `config_format` defaults to `auto`. `.yaml`/`.yml` is parsed as Clash/Mihomo; `.json` is distinguished by top-level keys; it can also be forced.

## Checks

| ID | Check | Failure |
| --- | --- | --- |
| `proxy_core` | Configured process name, client preset or a known proxy core is running | `fail` |
| `tun_adapter` | TUN adapter exists and is Up | `fail` |
| `default_route` | The lowest-metric `0.0.0.0/0` route goes through TUN | `fail` |
| `firewall_block` | All three firewall profiles are enabled with default outbound Block | `fail` |
| `guardian_rules` | Enabled allow rules meet the configured minimum | `degraded` |
| `core_ipv6` | The runtime config disables IPv6 | `degraded` |
| `strict_route` | The runtime config enables strict route | `degraded` |
| `dns_hijack` | The runtime config hijacks DNS on port 53 | `degraded` |
| `dns_servers` | Physical-adapter DNS equals the expected value | `degraded` |
| `os_ipv6` | IPv6 binding is disabled on physical adapters | `degraded` |

`overall`: any `fail` → `fail`; otherwise any `degraded` → `degraded`; all `ok` → `ok`; anything else → `unknown`.

`core_ipv6`, `strict_route` and `dns_hijack` are best-effort mappings: an unsupported format, a version-specific key name or an empty config stays `unknown` and needs a manual check.

## Configuration

Minimal example (FlClash):

```json
{
  "version": 1,
  "target": "YOUR-HOSTNAME",
  "proxy": {
    "client": "flclash",
    "process_names": ["FlClashCore"],
    "tun_adapter": "auto",
    "tun_match": [],
    "config_format": "auto",
    "runtime_config": "C:\\Users\\YOU\\AppData\\Roaming\\com.follow\\clash\\config.yaml"
  },
  "firewall": {
    "expect_default_block": true,
    "allow_rule_prefix": "guardian-",
    "min_allow_rules": 1
  },
  "network": {
    "expect_dns_servers": ["198.18.0.2"],
    "expect_ipv6_disabled": true
  },
  "alerts": {
    "cooldown_seconds": 120,
    "notify_states": ["fail", "degraded"],
    "interval_seconds": 5
  }
}
```

| Field | Required | Meaning |
| --- | --- | --- |
| `version` | yes | fixed `1` |
| `target` | yes | host name; must match `platform.node()` exactly |
| `proxy.client` | no | a preset above; `custom` or omitted means custom |
| `proxy.process_names` | no | overrides the preset; `[]` means any known core |
| `proxy.tun_adapter` | no | exact adapter name or `auto` (default) |
| `proxy.tun_match` | no | extra TUN name fragments, at most 8 |
| `proxy.config_format` | no | `auto`, `clash`, `sing-box` or `xray` |
| `proxy.runtime_config` | no | absolute path; `""` searches the default places of FlClash and Clash Verge Rev, otherwise the three config checks are `unknown` |
| `firewall.expect_default_block` | yes | require default outbound Block |
| `firewall.allow_rule_prefix` | yes | allow-rule name prefix |
| `firewall.min_allow_rules` | yes | minimum allow rules, 0–1000 |
| `network.expect_dns_servers` | yes | expected physical-adapter DNS, up to 8 IPv4 addresses |
| `network.expect_ipv6_disabled` | yes | require IPv6 disabled on physical adapters |
| `alerts.cooldown_seconds` | yes | notification cooldown, 0–86400 seconds |
| `alerts.notify_states` | yes | a combination of `fail`, `degraded`, `unknown` |
| `alerts.interval_seconds` | yes | collection interval, 2–3600 seconds |
| `alerts.paused` | no | pause notifications |

Runtime config paths differ by client and version; always point to the file the client actually loads. See [monitor.md](skills/claude-guardian/references/monitor.md) for common locations and the fields each format can express.

## UI and notifications

- **Native window**: dark sidebar navigation (Status / Log / Settings) + status cards + ttk settings controls; Settings adjusts the interval, cooldown, notification states and pause, and can open the JSON config directly.
- **Autostart**: a sidebar checkbox opens the panel hidden in the tray at login; off by default and removable at any time.
- **Fonts**: CJK-first stack: `MiSans` → `HarmonyOS Sans SC` → `Noto Sans SC` / Source Han Sans → `Microsoft YaHei UI` (ships with Windows), first one installed or dropped into `fonts/` wins; the Latin wordmark uses Anthropic Serif (if supplied) or Georgia, check codes Anthropic Mono / `Cascadia Mono` / `Consolas`. Body text no longer uses the CJK-less Anthropic Sans, which made mixed Chinese/Latin labels fall back glyph by glyph.
- **UI implementation**: `gui --ui auto` (default) prefers WebView and falls back to tkinter; `--ui web` is WebView only (error if unavailable), `--ui tk` is tkinter only.
- **Closing the window**: with a tray, hide to tray, close, or cancel; without a tray, only close or cancel.
- **Tray**: the shield changes colour with the overall state and shows the state on hover; transitions raise notifications with cooldown, and recovery is announced.
- **Web fallback**: `serve` listens on a random `127.0.0.1` port with a random session token, validates `Host`, `Origin` and `Sec-Fetch-Site`, and sends a strict CSP.
- **Notification name**: the tray runs in PowerShell and shows "Windows PowerShell" by default. Run `register-notifier` once to have notifications signed as CCGuard; `unregister-notifier` removes it.
- Focus Assist or Windows notification settings may suppress balloons; trust the panel.

## Troubleshooting

| Symptom | First step |
| --- | --- |
| Double-click does nothing | Install Python 3.10+ first; double-click `CCGuard.cmd` to see the fallback message; make sure `.pyw` is associated with `pythonw` |
| `quickstart` finds no client | Start the proxy client first, or pass `--client <preset>`; run `detect` to see candidates |
| `proxy_core` fails | Run `detect`; set the core process name explicitly with `process_names` |
| `tun_adapter` fails | Confirm the client TUN is on; run `detect`; add a `tun_match` fragment if needed |
| `default_route` fails | Confirm the default route goes through TUN; check for a higher-priority route or VPN |
| `core_ipv6` / `strict_route` / `dns_hijack` unknown | Open the card's "检测过程": if no runtime config was found, set `runtime_config` to the file the client actually loads; set `config_format` if needed |
| `dns_servers` / `os_ipv6` degraded | A subscription update or client upgrade may have restored DNS override or IPv6; recheck |
| Autostart does not work | Confirm the program directory and config path have not moved; toggle it again or run `autostart-enable`; check `CCGuard.lnk` in the current user's Startup folder |
| Fonts still look poor | Install MiSans or HarmonyOS Sans SC (or drop the font files into `fonts/`, loaded per process, not installed); the last fallback is `Microsoft YaHei UI` |
| The panel still looks old | pywebview or WebView2 is missing, so it fell back to tkinter; run `python -m pip install -r requirements-desktop.txt`; the new UI has a "历史" (history) page in the sidebar |
| No notifications | Check Windows notification settings and Focus Assist; the panel is the source of truth |
| "monitor stopped updating" | The monitor process exited or the interval is too long; restart the panel |
| The window will not open | tkinter is missing; use the `serve` web page |

## Project layout

```text
CCGuard.pyw                    double-click launcher (no console; repo root and release package)
CCGuard.cmd                    double-click fallback (pythonw / pyw / python / py)
skills/claude-guardian/
  SKILL.md                     Claude-Guardian Skill entry
  scripts/monitor.py           CCGuard monitor entry
  scripts/monitor_webview.py   WebView panel (pywebview bridge, default)
packaging/                     CCGuard.exe entry, PyInstaller spec and Inno Setup script
tools/build_windows.py         builds the exe and installer (same script as CI)
  scripts/monitor_history.py   state history (history.jsonl) and timelines
  scripts/monitor_guide.py     what each check looks at and how to fix it
  scripts/monitor_gui.py       tkinter panel (fallback)
  assets/monitor/              panel, tray, icons and config template
  references/monitor.md        monitor config, checks and boundaries
tests/                         unit, regression and synthetic interaction tests
tools/                         packaging, index and preview tools
docs/                          decision records and supplementary docs
```

## Versions and updates

- **Current version**: shown on the panel's "关于" (About) page, by `monitor.py --version`, and in `CCGuard.exe`'s file properties.
- **Update check**: on the About page click "检查更新"; it reads this repository's published releases from GitHub (no drafts or pre-releases) and lists newer versions with their notes; "去下载" opens the installer or release page in your browser. It goes online only when clicked, contacts only GitHub, and never downloads or installs by itself. CLI: `monitor.py update-check`.
- **Upgrading**: run the newer installer; it closes a running CCGuard first and keeps `monitor.json` and `history.jsonl`.
- **Update log**: the About page lists each version's main changes (bundled, works offline); the full development record is [CHANGELOG.md](CHANGELOG.md).
- **Numbering**: `major.minor.patch`; fixes bump the patch number, features bump the minor number. The version lives only in `skills/claude-guardian/scripts/version.py`, which the UI, CLI, exe properties and installer all read.

**Releasing** (maintainers):

1. Bump `__version__` in `version.py` and add the version's entry at the top of `assets/monitor/release-notes.json` (a test checks they match).
2. Update CHANGELOG, run the full suite, push to main, and wait for the three-platform CI and the installer build.
3. After the user confirms, publish a GitHub Release tagged `vX.Y.Z`. The `Windows installer` workflow fails if the tag differs from `version.py`; otherwise it builds, verifies and attaches the installer.
4. Download the published assets, check their hashes, and record the release in CHANGELOG.

## Development and verification

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
node tests/monitor-interaction.cjs
python -m compileall -q skills/claude-guardian/scripts
python tools/package_skill.py --output <new.zip>
```

- CI runs on Linux, macOS, Windows and Python 3.10 Linux; `tools/ci_scope.py` distinguishes docs-only from code pushes.
- Current version `0.6.0` (see Releases once published); `v0.5.1` made the setup wizard Simplified Chinese; since `v0.5.0` there is a Windows installer (no Python needed) and the data-source note on the exit page; since `v0.4.0` it includes the WebView UI, CJK fonts, state history, fix guidance, detection logs and the exit score. See [CHANGELOG.md](CHANGELOG.md) for the full record and [docs/decisions.md](docs/decisions.md) for design trade-offs.

## The full Claude-Guardian Skill

This repository also keeps the full Claude-Guardian Skill: subscription and account pacing, fixed egress IP, local / VM / VPS routes, firewall and route optimization, failure triage, cleanup planning and more. CCGuard covers Windows local monitoring only; those deployment and operations still follow the Skill's flow and tiered authorization.

- Skill entry: [skills/claude-guardian/SKILL.md](skills/claude-guardian/SKILL.md)
- Monitor reference: [monitor.md](skills/claude-guardian/references/monitor.md)
- Tiered authorization: [authorization-tiers.md](skills/claude-guardian/references/authorization-tiers.md)
- Local firewall: [local-firewall-prompts.md](skills/claude-guardian/references/local-firewall-prompts.md); the macOS PF script is accepted, with its scope at [local-firewall-prompts.md#mac](skills/claude-guardian/references/local-firewall-prompts.md#mac)
- Windows cleanup: [windows-cleanup.md](skills/claude-guardian/references/windows-cleanup.md)
- Contact and safety boundaries: [contact-and-safety.md](skills/claude-guardian/references/contact-and-safety.md)
- Device report template: [device-report.yml](.github/ISSUE_TEMPLATE/device-report.yml)

### Install the full Skill (macOS / Linux, optional)

CCGuard itself is Windows-only. If you also want the full Claude-Guardian Skill on macOS / Linux:

```bash
git clone https://github.com/SumitaRinku/CCguard.git Claude-Guardian
(
  set -eu
  skill_root="$HOME/.codex/skills"
  mkdir -p "$skill_root"
  if [ -e "$skill_root/claude-guardian" ] || [ -L "$skill_root/claude-guardian" ]; then
    printf '%s\n' 'Target exists; stopping. Inspect and back up the existing Skill, then migrate by hand.' >&2
    exit 1
  fi
  cp -R Claude-Guardian/skills/claude-guardian "$skill_root/claude-guardian"
)
```

You should end up with `~/.codex/skills/claude-guardian/SKILL.md`. The command stops on an existing target to avoid nested copies or overwriting customizations.

## Ground rules

- **Money and accounts are yours**: you pay, sign up, log in and do KYC or OAuth yourself.
- **No credentials needed**: you never hand over IPs, subscription links, passwords, UUIDs or full configs.
- **No Claude during preparation**: the client is not started, logged into or contacted.
- **Adapt to your environment**: systems, clients and versions differ; check first, adapt, and roll back if something goes wrong.
- **Autostart is an explicit switch**: it is off by default; only ticking it or running `autostart-enable` writes one per-user Startup shortcut, and it can be removed at any time.
- **Nobody can guarantee you will not be banned**: CCGuard monitors local state only; it is not a ban-avoidance guarantee and does not replace platform compliance or acceptance.

See [authorization tiers](skills/claude-guardian/references/authorization-tiers.md) and [contact and authorization boundaries](skills/claude-guardian/references/contact-and-safety.md) for the full rules.

## Documentation

| Start here | Contents |
| --- | --- |
| [Monitor reference](skills/claude-guardian/references/monitor.md) | Configuration, client presets, checks, notifications and boundaries |
| [How checks work](skills/claude-guardian/references/monitor.md#principles) | Data source, rule and detection log for every check; requests and privacy of the exit score |
| [Script index](skills/claude-guardian/references/scripts-index.md) | Monitor and Claude-Guardian script entries |
| [Decision log](docs/decisions.md) | ADRs and implementation trade-offs |
| [Changelog](CHANGELOG.md) | What changed per version, verification and rollback |
| [Claude-Guardian upstream](https://github.com/DUNHKpcc/Claude-Guardian) | Full Skill, source library and route docs |
| [Releases](https://github.com/SumitaRinku/CCguard/releases) | Packages and checksums |

## Feedback

Report problems through [Issues](https://github.com/SumitaRinku/CCguard/issues). Include the Windows version, proxy client and version, reproduction steps and expected result; keep accounts, credentials, subscription links and full configs out of it. A device report can follow [device-report.yml](.github/ISSUE_TEMPLATE/device-report.yml).

## Data sources and credits

- The **exit score**'s trust score, IP type, location, network and risk flags come from the public API of [ip.net.coffee](https://ip.net.coffee/claude/); the score bands and restricted-region rule follow its Claude IP check page. Open that site in your browser for the full check (Claude exit IP, DNS and WebRTC leaks).
- The **exit IP** comes from Cloudflare's `1.1.1.1/cdn-cgi/trace`.
- Both are third-party services that CCGuard only contacts when you click "检测"; if they change, the exit score shows "检测失败" and local monitoring is unaffected.
- The installer wizard's Simplified Chinese translation is the community translation carried in the official Inno Setup repository ([jrsoftware/issrc](https://github.com/jrsoftware/issrc), `Files/Languages/Unofficial/ChineseSimplified.isl`, maintained by Kira), kept with its credits.
- The project is maintained on top of [Claude-Guardian](https://github.com/DUNHKpcc/Claude-Guardian).

## License

Code is licensed **GPL-3.0-only**, see [LICENSE](LICENSE). Source originals keep their existing attribution and license notices. CCGuard is not affiliated with Anthropic and makes no ban-avoidance guarantee.
