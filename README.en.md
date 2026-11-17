<div align="center">

<img src="skills/claude-guardian/assets/monitor/logo-ok.png" width="96" height="96" alt="CCGuard shield">

# CCGuard

**A read-only Windows status panel for your proxy, TUN, route, firewall, DNS and IPv6.**

No outbound requests · No system changes · No admin rights · No background service

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

It splits the state into 10 checks and shows them in green / orange / red / grey in a window, a tray icon and an optional local web page; it raises a system notification when a key check fails. The monitor does not change the firewall, restart the proxy, edit the configuration or make any outbound request, so it is safe to leave running.

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
| **Window + tray + web** | WebView panel (default) / tkinter panel (fallback), tray notifications, local `127.0.0.1` web page as an alternative |
| **System notifications** | Alerts on state transitions with cooldown and recovery notices; can be paused |
| **Optional autostart** | A per-user Startup shortcut opens the panel hidden in the tray at login; off by default |
| **Client presets** | FlClash, Clash Verge Rev, Clash Nyanpasu, Clash for Windows, Mihomo / Clash.Meta, sing-box, Hiddify, v2rayN, NekoRay / NekoBox |
| **TUN auto-detection** | Matches adapter name / description fragments, so client upgrades usually need no config change |
| **Multiple config formats** | Clash/Mihomo YAML, sing-box JSON (including 1.11+ `address`), Xray JSON; unreadable fields stay `unknown` |
| **Candidate detection** | `monitor.py detect` lists candidate cores, TUN adapters and client presets without a config |

## Safety boundaries

- **Read-only**: no `Set-*`, no firewall/route/proxy changes, no core restart.
- **No outbound traffic**: no IP, DNS-leak, latency or WebRTC probes; the web mode only listens on `127.0.0.1`.
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

Download [`claude-guardian-0.3.0.zip`](https://github.com/SumitaRinku/CCguard/releases/download/v0.3.0/claude-guardian-0.3.0.zip), extract it, and double-click `CCGuard.pyw` or `CCGuard.cmd` inside `claude-guardian\`.

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

The quick config does not check the allow-rule count or expected DNS servers by default; add them in Settings or the JSON. An empty `runtime_config` leaves the three config checks `unknown`.

### 5. Manual configuration (optional)

To fill it in yourself, run `detect` first to see candidate cores and TUN adapters:

```bat
python ...\monitor.py detect
```

Then copy `assets\monitor\config.example.json` to a private directory outside the repository (for example `%USERPROFILE%\.ccguard\monitor.json`) and confirm at least:

- `target`: the exact output of `python -c "import platform; print(platform.node())"`
- `proxy.client`: a preset from the table below
- `proxy.tun_adapter`: keep `auto`; fill the exact adapter name only when detection fails
- `proxy.runtime_config`: the absolute path of the config the client actually loads; leave it empty to skip the three config checks
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
:: one collection, JSON output
python ...\monitor.py check --config <private>\monitor.json

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
| `proxy.runtime_config` | no | absolute path; `""` disables the three config checks |
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
| `core_ipv6` / `strict_route` / `dns_hijack` unknown | Check that `runtime_config` points to the live config; set `config_format` if needed |
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
  scripts/monitor_history.py   state history (history.jsonl) and timelines
  scripts/monitor_guide.py     what each check looks at and how to fix it
  scripts/monitor_gui.py       tkinter panel (fallback)
  assets/monitor/              panel, tray, icons and config template
  references/monitor.md        monitor config, checks and boundaries
tests/                         unit, regression and synthetic interaction tests
tools/                         packaging, index and preview tools
docs/                          decision records and supplementary docs
```

## Development and verification

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
node tests/monitor-interaction.cjs
python -m compileall -q skills/claude-guardian/scripts
python tools/package_skill.py --output <new.zip>
```

- CI runs on Linux, macOS, Windows and Python 3.10 Linux; `tools/ci_scope.py` distinguishes docs-only from code pushes.
- Latest release `v0.3.0`; it includes double-click start, quickstart, autostart and the UI improvements. See [CHANGELOG.md](CHANGELOG.md) for the full record and [docs/decisions.md](docs/decisions.md) for design trade-offs.

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
| [Script index](skills/claude-guardian/references/scripts-index.md) | Monitor and Claude-Guardian script entries |
| [Decision log](docs/decisions.md) | ADRs and implementation trade-offs |
| [Changelog](CHANGELOG.md) | What changed per version, verification and rollback |
| [Claude-Guardian upstream](https://github.com/DUNHKpcc/Claude-Guardian) | Full Skill, source library and route docs |
| [Releases](https://github.com/SumitaRinku/CCguard/releases) | Packages and checksums |

## Feedback

Report problems through [Issues](https://github.com/SumitaRinku/CCguard/issues). Include the Windows version, proxy client and version, reproduction steps and expected result; keep accounts, credentials, subscription links and full configs out of it. A device report can follow [device-report.yml](.github/ISSUE_TEMPLATE/device-report.yml).

## License

Code is licensed **GPL-3.0-only**, see [LICENSE](LICENSE). Source originals keep their existing attribution and license notices. CCGuard is not affiliated with Anthropic and makes no ban-avoidance guarantee.
