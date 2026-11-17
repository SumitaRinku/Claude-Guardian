<div align="center">

<img src="skills/claude-guardian/assets/monitor/logo-ok.png" width="96" height="96" alt="CCGuard shield">

# CCGuard

**Windows 本机只读监测面板：代理、TUN、路由、防火墙、DNS 与 IPv6，一眼看清。**

监测不出站 · 出口评分手动触发 · 不改系统 · 不需要管理员

<p>
  <img alt="Windows 10/11" src="https://img.shields.io/badge/Windows-10%2F11-0078D4?style=flat-square">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white">
  <img alt="GPL-3.0-only" src="https://img.shields.io/badge/License-GPL--3.0--only-2E7D32?style=flat-square">
  <a href="https://github.com/SumitaRinku/CCguard/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/SumitaRinku/CCguard?style=flat-square"></a>
</p>

**中文** · [English](README.en.md)

[快速开始](#快速开始) · [检查项](#检查项) · [支持客户端](#支持的代理客户端) · [配置](#配置) · [安全边界](#安全边界) · [文档](#文档) · [开发](#开发与验证)

</div>

---

## CCGuard 是什么

CCGuard 是本仓库在 [Claude-Guardian](https://github.com/DUNHKpcc/Claude-Guardian) 基础上维护的 Windows 本机只读监测面板。它面向已经部署好代理、TUN 和防火墙的环境，持续回答一个问题：**现在这台机器上的防护还在不在？**

它把状态拆成 10 项检查，用绿 / 橙 / 红 / 灰显示在窗口、托盘和可选网页里；关键项失效时用系统通知提醒。监测本身不修改防火墙、不重启代理、不改配置，10 项检查也不发起出站请求，适合长期开着；需要看出口 IP 质量时，再手动点一次出口评分。

> 监测通过只说明本机状态与配置符合预期，不代表出口 IP、DNS、账号或平台验收通过；它不承诺免封，也不替代 Claude-Guardian 的部署与分级授权流程。

## 主要能力

| 能力 | 说明 |
| --- | --- |
| **10 项实时检查** | 代理核心、TUN、默认路由、防火墙、放行规则、核心 IPv6 / 严格路由 / DNS 接管、物理网卡 DNS / IPv6 |
| **双击启动** | Release 包解压后双击 `CCGuard.pyw`（或 `CCGuard.cmd`），首次自动生成配置并打开面板；再次双击不会开第二个窗口 |
| **一条命令启动** | `quickstart` 自动识别主机、客户端和 TUN，生成配置并打开面板；已有配置不覆盖 |
| **状态色盾牌** | 绿 ✓ 正常、橙 ! 降级、红 ✕ 失效、灰 — 未知；窗口、托盘与网页标题同步 |
| **新界面** | WebView（pywebview + Edge WebView2）桌面面板：状态横幅、侧栏异常计数、彩色日志、跟随系统深色模式，窗口按内容自动定尺寸；没装 pywebview 时自动回退 tkinter 面板 |
| **状态历史** | 每项检查最近 24 小时／7 天的状态时间线，未运行监测的时段单独标出；记录存在配置旁的 `history.jsonl`，只含检查项和状态，保留 7 天 |
| **处理指引** | 点开任一检查卡片，查看它检查什么、当前结果对应的处理步骤、这一项最近 24 小时的变化和结果代码 |
| **检测日志** | 每项检查都记下读了哪条系统查询、看到了什么、为什么判成这个状态，在卡片详情的“检测过程”里逐条列出；不含 IP 和文件路径。原理见 [检测原理](skills/claude-guardian/references/monitor.md#principles) |
| **出口评分** | “出口”页手动检测：经当前网络向 Cloudflare 取出口 IP，再从 [ip.net.coffee](https://ip.net.coffee/claude/) 取信任分、IP 类型、地区、运营商和风险标记，并列出每一步请求；可一键在浏览器打开完整详情。不访问 Claude，见 [出口评分](skills/claude-guardian/references/monitor.md#exit-score) |
| **窗口 + 托盘 + 网页** | WebView 面板（默认）／tkinter 面板（回退）、托盘通知、`127.0.0.1` 本地网页备选 |
| **系统通知** | 状态跃迁时提醒，带冷却与恢复提示；可暂停 |
| **可选开机自启** | 当前用户 Startup 快捷方式，登录后隐藏到托盘；默认关闭，可随时撤销 |
| **多客户端预设** | FlClash、Clash Verge Rev、Clash Nyanpasu、Clash for Windows、Mihomo / Clash.Meta、sing-box、Hiddify、v2rayN、NekoRay / NekoBox |
| **TUN 自动识别** | 按网卡名称 / 描述片段识别，客户端升级后通常不用改配置 |
| **多配置格式** | Clash/Mihomo YAML、sing-box JSON（含 1.11+ `address`）、Xray JSON；读不出记 `unknown` |
| **候选识别** | `monitor.py detect` 无配置列出候选核心、TUN 网卡和可能的客户端预设 |

## 安全边界

- **只读**：不调用 `Set-*`，不改防火墙、路由、代理配置，不重启核心。
- **监测不出站**：10 项检查只读本机，不发起联网请求，不做 DNS 泄露、延迟或 WebRTC 测试；网页模式只监听 `127.0.0.1`。
- **出口评分只在你点击时联网**：只请求 `1.1.1.1/cdn-cgi/trace` 和 `ip.net.coffee/api/iprisk`，不访问 claude.ai 或 anthropic.com；出口 IP 会发给 ip.net.coffee，界面只显示前两段。完整验收页由你在自己的浏览器里打开。
- **不要求管理员**：监测以普通用户运行；提权只属于其他防护脚本。
- **默认不常驻、不自启**：不建 Windows 服务或计划任务，默认不写 Startup。只有你显式开启「开机自启」时，才在当前用户 Startup 目录创建一个 CCGuard 快捷方式，可随时用 `autostart-disable` 或在面板左侧栏关闭。
- **不碰凭据**：通知和状态只含状态枚举与检查项名称，不含 IP、路径、节点、订阅链接或配置值。
- **`unknown` 不等于正常**：查询失败、权限不足、格式不支持或配置留空一律显示未知，不推测为通过。

## 快速开始

### 1. 准备

- Windows 10 / 11，PowerShell 5.1
- 用安装程序时不需要 Python；用 Release 包或源码时需要 Python 3.10+（官方安装包通常自带 tkinter）
- 可选（仅 Release 包与源码）：`python -m pip install -r requirements-desktop.txt` 安装 pywebview，获得 WebView 新界面（Windows 10/11 自带 Edge WebView2）；不装也能用，自动回退 tkinter 面板
- 代理客户端已经在运行，TUN 和防火墙已按你的方案部署

监测面板只用 Python 标准库，不需要安装第三方依赖。

### 2. 获取

**方式 A：安装程序（推荐）**

下载 [`CCGuard-Setup-0.6.0.exe`](https://github.com/SumitaRinku/CCguard/releases/download/v0.6.0/CCGuard-Setup-0.6.0.exe)，双击安装。不需要 Python，也不需要管理员：程序装到当前用户的 `%LOCALAPPDATA%\Programs\CCGuard`，带开始菜单和桌面图标，可在“设置 → 应用 → 已安装的应用”里卸载。卸载会删掉程序、快捷方式和开机自启项，保留你的 `monitor.json` 与 `history.jsonl`。

安装程序在 GitHub Actions 上从源码构建，安装、自检、卸载验证通过后才附到 Release，同目录的 `SHA256SUMS-installer-0.6.0.txt` 可核对哈希。安装程序没有代码签名，首次运行时 Windows SmartScreen 可能提示“Windows 已保护你的电脑”，点“更多信息 → 仍要运行”即可。

**方式 B：Release 包（Python 版，双击即用）**

下载 [`claude-guardian-0.6.0.zip`](https://github.com/SumitaRinku/CCguard/releases/download/v0.6.0/claude-guardian-0.6.0.zip)，解压后得到 `claude-guardian\` 目录。双击其中的 `CCGuard.pyw` 或 `CCGuard.cmd` 即可。

**方式 C：克隆仓库（最新源码）**

```powershell
git clone https://github.com/SumitaRinku/CCguard.git
```

仓库根目录也可以直接双击 `CCGuard.pyw` / `CCGuard.cmd`；监测入口是 `skills\claude-guardian\scripts\monitor.py`。

### 3. 双击启动

用安装程序的，从开始菜单或桌面打开 CCGuard 即可。用 Release 包的，解压后，进入 `claude-guardian\`，双击：

- `CCGuard.pyw`：无控制台，推荐；需要 `.pyw` 关联到 Python。
- `CCGuard.cmd`：找不到 `pythonw` / `pyw` 时回退到 `python` / `py`；会短暂闪一下控制台。

首次运行会自动生成 `%LOCALAPPDATA%\CCGuard\monitor.json` 并打开面板，不需要命令行。再次双击不会开第二个窗口；已在运行时会提示从托盘打开。

### 4. 命令行启动（等价）

```bat
:: 仓库内
python skills\claude-guardian\scripts\monitor.py quickstart
```

`quickstart` 会读取本机主机名，识别正在运行的已知客户端与 TUN，在 `%LOCALAPPDATA%\CCGuard\monitor.json` 生成配置（已有配置不覆盖），然后打开面板 + 托盘。关掉窗口后托盘继续提醒。

常用选项：

```bat
:: 指定客户端预设
python ...\monitor.py quickstart --client flclash

:: 指定客户端实际加载的运行配置（绝对路径）
python ...\monitor.py quickstart --runtime-config "C:\Users\YOU\AppData\Roaming\com.follow\clash\config.yaml"

:: 只生成配置，不打开面板
python ...\monitor.py quickstart --no-launch

:: 同时开启开机自启（登录后隐藏到托盘）
python ...\monitor.py quickstart --autostart
```

快速配置默认不校验放行规则数量和 DNS 期望值；需要时在面板设置页或 JSON 里补。`runtime_config` 留空时，会在 FlClash、Clash Verge Rev 的默认位置自动查找运行配置；其他客户端或找不到时，三项配置检查显示 `unknown`，需要手动填写。

### 5. 手动配置（可选）

想自己填写时，先运行 `detect` 看候选核心和 TUN：

```bat
python ...\monitor.py detect
```

然后把 `assets\monitor\config.example.json` 复制到仓库外（例如 `%USERPROFILE%\.ccguard\monitor.json`），至少确认：

- `target`：`python -c "import platform; print(platform.node())"` 的精确输出
- `proxy.client`：下表中的客户端预设
- `proxy.tun_adapter`：保持 `auto`；识别不到时再填精确网卡名
- `proxy.runtime_config`：客户端实际加载的配置绝对路径；留空时自动查找 FlClash、Clash Verge Rev 的默认位置
- `firewall.allow_rule_prefix`、`network.expect_dns_servers`：按你的部署填写

不要把订阅、节点、密码或令牌写进去；配置里没有这些字段。

### 6. 启动、自启与关闭

```bat
:: 打开面板 + 托盘
python ...\monitor.py gui --config "%LOCALAPPDATA%\CCGuard\monitor.json" --tray

:: 开启 / 关闭 / 查看开机自启
python ...\monitor.py autostart-enable --config "%LOCALAPPDATA%\CCGuard\monitor.json"
python ...\monitor.py autostart-disable
python ...\monitor.py autostart-status
```

面板左侧栏也有「开机自启」复选框，效果与命令相同。默认关闭；开启后登录 Windows 会自动打开面板并隐藏到托盘，不会弹出窗口。

其他入口：

```bat
:: 单次采集，输出 JSON（每项含 source 与 evidence 检测过程）
python ...\monitor.py check --config <private>\monitor.json

:: 出口评分（联网：Cloudflare trace + ip.net.coffee，不访问 Claude；不需要配置）
python ...\monitor.py ip-score

:: 本地网页（只监听 127.0.0.1，带随机会话令牌）
python ...\monitor.py serve --config <private>\monitor.json

:: 生成桌面 / 开始菜单入口（不写自启）
python ...\monitor.py desktop --config <private>\monitor.json --output <new-dir>

:: 让通知以 CCGuard 署名（当前用户开始菜单建一个入口）
python ...\monitor.py register-notifier --config <private>\monitor.json
```

## 支持的代理客户端

`proxy.client` 可选内置预设，预设自动填入进程名、TUN 名称片段和配置格式；`process_names`、`tun_adapter`、`config_format` 仍可覆盖。

| `client` | 默认进程名（节选） | TUN 名称片段（节选） | 配置格式 |
| --- | --- | --- | --- |
| `flclash` | `FlClashCore`、`FlClash` | `flclash`、`meta tunnel` | Clash YAML |
| `clash-verge-rev` | `verge-mihomo`、`clash-verge` | `clash`、`mihomo`、`meta` | Clash YAML |
| `clash-nyanpasu` | `clash-nyanpasu`、`mihomo` | `nyanpasu`、`mihomo` | Clash YAML |
| `clash-for-windows` | `Clash for Windows`、`clash-win64` | `clash` | Clash YAML |
| `mihomo` | `mihomo`、`clash-meta` | `mihomo`、`meta tunnel` | Clash YAML |
| `sing-box` | `sing-box` | `sing-box`、`sing-tun` | sing-box JSON |
| `hiddify` | `Hiddify`、`HiddifyCli`、`sing-box` | `hiddify`、`sing-tun` | sing-box JSON |
| `v2rayn` | `v2rayN`、`xray`、`v2ray` | `v2rayn`、`tun2socks` | Xray JSON |
| `nekoray` | `nekoray`、`nekobox`、`sing-box`、`xray` | `nekoray`、`nekobox` | 自动 |

- **TUN 自动识别**：`tun_adapter` 默认 `auto`，按网卡名称和描述里的片段匹配；完全对不上时用 `tun_match` 加片段。
- **进程名**：`process_names` 不填时用预设；显式填写优先；`client` 与 `process_names` 都不填时，任一已知代理核心在运行就算通过。
- **配置格式**：`config_format` 默认 `auto`。`.yaml`/`.yml` 按 Clash/Mihomo 解析；`.json` 按顶层键区分 sing-box 与 Xray；也可以强制指定。

## 检查项

| ID | 检查 | 失败时 |
| --- | --- | --- |
| `proxy_core` | 配置的进程名、客户端预设或已知代理核心是否在运行 | `fail` |
| `tun_adapter` | TUN 网卡存在且 Up | `fail` |
| `default_route` | `0.0.0.0/0` 最低度量路由是否走 TUN | `fail` |
| `firewall_block` | 三档防火墙启用且默认出站为 Block | `fail` |
| `guardian_rules` | 启用的放行规则数量是否达到配置下限 | `degraded` |
| `core_ipv6` | 运行配置是否关闭 IPv6 | `degraded` |
| `strict_route` | 运行配置是否开严格路由 | `degraded` |
| `dns_hijack` | 运行配置是否接管 53 端口 DNS | `degraded` |
| `dns_servers` | 物理网卡 DNS 等于期望值 | `degraded` |
| `os_ipv6` | 物理网卡 IPv6 绑定已禁用 | `degraded` |

`overall`：任一 `fail` → `fail`；否则任一 `degraded` → `degraded`；全部 `ok` → `ok`；其余 → `unknown`。

`core_ipv6`、`strict_route`、`dns_hijack` 是尽力而为的映射：格式不支持、键名版本不同或配置留空时记 `unknown`，需人工核对。

## 配置

最小示例（FlClash）：

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

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `version` | 是 | 固定 `1` |
| `target` | 是 | 主机名，必须与 `platform.node()` 完全一致 |
| `proxy.client` | 否 | 上表预设；`custom` 或省略表示自定义 |
| `proxy.process_names` | 否 | 覆盖预设；`[]` 表示任一已知核心 |
| `proxy.tun_adapter` | 否 | 精确网卡名或 `auto`（默认） |
| `proxy.tun_match` | 否 | 额外 TUN 名称片段，最多 8 个 |
| `proxy.config_format` | 否 | `auto`、`clash`、`sing-box`、`xray` |
| `proxy.runtime_config` | 否 | 绝对路径；`""` 时自动查找 FlClash、Clash Verge Rev 的默认位置，找不到则三项配置检查为 `unknown` |
| `firewall.expect_default_block` | 是 | 是否要求默认出站 Block |
| `firewall.allow_rule_prefix` | 是 | 放行规则名前缀 |
| `firewall.min_allow_rules` | 是 | 放行规则数量下限，0–1000 |
| `network.expect_dns_servers` | 是 | 期望的物理网卡 DNS，最多 8 个 IPv4 |
| `network.expect_ipv6_disabled` | 是 | 是否要求物理网卡关闭 IPv6 |
| `alerts.cooldown_seconds` | 是 | 通知冷却，0–86400 秒 |
| `alerts.notify_states` | 是 | `fail`、`degraded`、`unknown` 的组合 |
| `alerts.interval_seconds` | 是 | 采集间隔，2–3600 秒 |
| `alerts.paused` | 否 | 暂停提醒 |

运行配置路径因客户端和版本而异，必须指向客户端实际加载的那一份；常见位置与各格式可读字段见 [monitor.md](skills/claude-guardian/references/monitor.md)。

## 界面与通知

- **独立窗口**：左侧栏导航（状态 / 日志 / 设置）+ 状态卡片 + ttk 设置控件；设置页可调采集间隔、通知冷却、通知项和暂停提醒，并可「打开配置」直接编辑 JSON。
- **开机自启**：左侧栏「开机自启」复选框，登录后自动打开面板并隐藏到托盘；默认关闭，可随时取消。
- **字体**：安装版自带思源黑体（Noto Sans SC，SIL OFL 1.1），界面在所有电脑上一致，不依赖系统装了什么字体。Python 版不带字体文件，按已安装字体选：`Noto Sans SC` → `MiSans` → `HarmonyOS Sans SC` → 思源黑体 → `Microsoft YaHei UI`（Windows 自带）。英文字标用 Anthropic Serif（自备时）或 Georgia，检查码用 Anthropic Mono／`Cascadia Mono`／`Consolas`。
- **界面实现**：`gui --ui auto`（默认）优先 WebView，失败回退 tkinter；`--ui web` 只用 WebView（不可用时报错），`--ui tk` 只用 tkinter。
- **关闭窗口**：有托盘时可隐藏到托盘、直接关闭或取消；没有托盘时只提供关闭或取消。
- **托盘**：盾牌图标随整体状态换色，悬停显示状态；状态跃迁时按冷却发系统通知，恢复也提示。
- **网页备选**：`serve` 只监听 `127.0.0.1` 的随机端口，路径带随机会话令牌，并校验 `Host`、`Origin`、`Sec-Fetch-Site`，带严格 CSP。
- **通知署名**：托盘运行在 PowerShell 中，默认显示「Windows PowerShell」。执行一次 `register-notifier` 后，通知以 CCGuard 署名；撤销用 `unregister-notifier`。
- 专注助手或系统通知设置可能吞掉气泡；以面板显示为准。

## 常见问题

| 现象 | 先做什么 |
| --- | --- |
| 双击没反应 | 先装 Python 3.10+；改双击 `CCGuard.cmd` 看提示；确认 `.pyw` 已关联到 `pythonw` |
| `quickstart` 没识别到客户端 | 先启动代理客户端，或用 `--client <预设>` 指定；也可先跑 `detect` 看候选 |
| `proxy_core` 失效 | 运行 `detect` 看核心进程名；用 `process_names` 显式填写 |
| `tun_adapter` 失效 | 确认客户端 TUN 已开启；用 `detect` 看网卡名；必要时加 `tun_match` |
| `default_route` 失效 | 确认默认路由走 TUN；检查是否有更高优先级的路由或 VPN |
| `core_ipv6` / `strict_route` / `dns_hijack` 未知 | 点开卡片看“检测过程”：没找到运行配置时，在配置里填 `runtime_config` 为客户端实际加载的文件；必要时指定 `config_format` |
| `dns_servers` / `os_ipv6` 降级 | 订阅更新或客户端升级可能改回 DNS 覆写或 IPv6；恢复后重新核对 |
| 开机自启没生效 | 确认程序目录和配置路径没有移动；重新勾选或用 `autostart-enable`；检查当前用户 Startup 目录里的 `CCGuard.lnk` |
| 字体仍不好看 | 用安装版（自带思源黑体）；Python 版可安装 Noto Sans SC 或 MiSans 到系统，最低回退为 `Microsoft YaHei UI` |
| 面板还是旧样式 | 没装 pywebview 或缺 WebView2，已回退 tkinter；执行 `python -m pip install -r requirements-desktop.txt`；新界面左侧有“历史”页 |
| 收不到通知 | 检查 Windows 通知设置与专注助手；面板显示才是准的 |
| 提示「监测已停止更新」 | 监测进程已退出或采集间隔过长；重新启动面板 |
| 窗口打不开 | 缺少 tkinter；改用 `serve` 网页版 |

## 项目结构

```text
CCGuard.pyw                    双击启动（无控制台；仓库根和 Release 包内各一份）
CCGuard.cmd                    双击回退（找 pythonw / pyw / python / py）
skills/claude-guardian/
  SKILL.md                     Claude-Guardian Skill 入口
  scripts/monitor.py           CCGuard 监测入口
  scripts/monitor_webview.py   WebView 面板（pywebview 桥接，默认）
packaging/                     CCGuard.exe 入口、PyInstaller 配置与 Inno Setup 安装脚本
tools/build_windows.py         构建 exe 与安装程序（CI 同一脚本）
  scripts/monitor_history.py   状态历史（history.jsonl）与时间线
  scripts/monitor_guide.py     各检查项的说明与处理步骤
  scripts/monitor_gui.py       tkinter 面板（回退）
  assets/monitor/              面板、托盘、图标与配置模板
  references/monitor.md        监测配置、检查项与边界
tests/                         单元、回归与合成交互测试
tools/                         打包、索引与预览工具
docs/                          决策记录与补充文档
```

## 版本与更新

- **查看版本**：面板“关于”页显示当前版本；命令行 `monitor.py --version`；安装版也写在 `CCGuard.exe` 的文件属性里。
- **检查更新**：“关于”页点“检查更新”，向 GitHub 读取本仓库已发布的版本（不含草稿和预发布），列出比当前新的版本和它们的发布说明；“去下载”在浏览器里打开安装程序或发布页。只在点击时联网，只访问 GitHub，不自动下载、不自动安装。命令行：`monitor.py update-check`。
- **升级**：运行新版本的安装程序即可覆盖安装，会先关闭正在运行的 CCGuard，保留 `monitor.json` 与 `history.jsonl`。
- **更新日志**：“关于”页列出每个版本的主要变化（随程序打包，离线可看）；完整开发记录见 [CHANGELOG.md](CHANGELOG.md)。
- **版本号规则**：`主版本.次版本.修订号`。只修问题升修订号，加功能升次版本号。版本号只写在 `skills/claude-guardian/scripts/version.py` 一处，界面、命令行、exe 属性和安装程序都读它。

**发布新版本的步骤**（维护者）：

1. 改 `version.py` 的 `__version__`，并在 `assets/monitor/release-notes.json` 最前面加这个版本的更新日志（测试会检查两者一致）。
2. 写 CHANGELOG，跑完整测试，推送到 main，等推送 CI 和安装程序构建都通过。
3. 用户确认后，发布 GitHub Release，标签 `vX.Y.Z`。`Windows installer` 工作流发现标签与 `version.py` 不一致会直接失败，一致才构建、验证并附上安装程序。
4. 下载发布的资产核对哈希，把发布记录写进 CHANGELOG。

## 开发与验证

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
node tests/monitor-interaction.cjs
python -m compileall -q skills/claude-guardian/scripts
python tools/package_skill.py --output <new.zip>
```

- CI 按改动范围选择平台（`tools/ci_scope.py`）：只改文档跑 Linux；只改 CCGuard（面板、打包与其测试）跑 Linux 和 Windows；改到 Skill 其他部分或共用代码跑 Linux、macOS、Windows。另有 Python 3.10 Linux 运行时检查。
- 最新发布 `v0.6.0`：运行配置自动查找（修复安装版三项显示“未知”）、版本号、检查更新与更新日志；`v0.5.1` 安装向导改为简体中文；`v0.5.0` 起提供 Windows 安装程序（不需要 Python）与出口页来源说明；`v0.4.0` 起包含 WebView 新界面、中文字体、状态历史、处理指引、检测日志与出口评分。完整记录见 [CHANGELOG.md](CHANGELOG.md)，设计取舍见 [docs/decisions.md](docs/decisions.md)。

## 完整 Claude-Guardian Skill

本仓库同时保留完整的 Claude-Guardian Skill：订阅与账号节奏、固定出口 IP、本机 / VM / VPS 三条路线、防火墙与线路优化、故障分流、清理规划等。CCGuard 只负责 Windows 本机监测；上面这些部署与操作仍按 Skill 的流程和分级授权执行。

- Skill 入口：[skills/claude-guardian/SKILL.md](skills/claude-guardian/SKILL.md)
- 监测说明：[monitor.md](skills/claude-guardian/references/monitor.md)
- 分级授权：[authorization-tiers.md](skills/claude-guardian/references/authorization-tiers.md)
- 本机防火墙：[local-firewall-prompts.md](skills/claude-guardian/references/local-firewall-prompts.md)；macOS PF 脚本已验收，范围见 [local-firewall-prompts.md#mac](skills/claude-guardian/references/local-firewall-prompts.md#mac)
- Windows 清理：[windows-cleanup.md](skills/claude-guardian/references/windows-cleanup.md)
- 接触与安全边界：[contact-and-safety.md](skills/claude-guardian/references/contact-and-safety.md)
- 真机反馈模板：[device-report.yml](.github/ISSUE_TEMPLATE/device-report.yml)

### 安装完整 Skill（macOS / Linux，可选）

CCGuard 本身只支持 Windows。如果你也要在 macOS / Linux 上使用完整的 Claude-Guardian Skill：

```bash
git clone https://github.com/SumitaRinku/CCguard.git Claude-Guardian
(
  set -eu
  skill_root="$HOME/.codex/skills"
  mkdir -p "$skill_root"
  if [ -e "$skill_root/claude-guardian" ] || [ -L "$skill_root/claude-guardian" ]; then
    printf '%s\n' '目标已存在，停止安装；请先检查并备份现有 Skill，再手动迁移。' >&2
    exit 1
  fi
  cp -R Claude-Guardian/skills/claude-guardian "$skill_root/claude-guardian"
)
```

最终应有 `~/.codex/skills/claude-guardian/SKILL.md`。遇到已有目标会停止，避免嵌套复制或覆盖自定义内容。

## 几条底线

- **钱和账号你来**：付款、注册、登录、KYC、OAuth 都由你本人完成。
- **不要你的凭据**：不用交出 IP、订阅链接、密码、UUID 或完整配置。
- **准备阶段不碰 Claude**：不启动客户端、不登录、不访问其服务。
- **按你的环境调整**：系统、客户端和版本可能不同，先核对再操作，出问题就回滚。
- **开机自启是显式开关**：默认关闭；只有你勾选或执行 `autostart-enable` 时才写一个当前用户 Startup 快捷方式，可随时撤销。
- **没人能保证免封**：CCGuard 只监测本机状态，不承诺免封，也不替代平台合规与验收。

完整规则见 [分级授权](skills/claude-guardian/references/authorization-tiers.md) 与 [接触与授权边界](skills/claude-guardian/references/contact-and-safety.md)。

## 文档

| 从这里开始 | 内容 |
| --- | --- |
| [监测说明](skills/claude-guardian/references/monitor.md) | 配置、客户端预设、检查项、通知与边界 |
| [检测原理](skills/claude-guardian/references/monitor.md#principles) | 每项检查的数据来源、判定规则与检测日志；出口评分的请求与隐私 |
| [脚本索引](skills/claude-guardian/references/scripts-index.md) | 监测与 Claude-Guardian 脚本入口 |
| [决策记录](docs/decisions.md) | ADR 与实现取舍 |
| [更新记录](CHANGELOG.md) | 每个版本改了什么、验证与回滚 |
| [Claude-Guardian 上游](https://github.com/DUNHKpcc/Claude-Guardian) | 完整 Skill、资料库与路线文档 |
| [Releases](https://github.com/SumitaRinku/CCguard/releases) | 安装包与校验和 |

## 反馈

欢迎通过 [Issues](https://github.com/SumitaRinku/CCguard/issues) 反馈问题。请说明 Windows 版本、代理客户端与版本、复现步骤和预期结果；账号、凭据、订阅链接和完整配置不要贴出来。真机反馈可参考 [device-report.yml](.github/ISSUE_TEMPLATE/device-report.yml)。

## 数据来源与致谢

- **出口评分**的信任分、IP 类型、地区、运营商与风险标记来自 [ip.net.coffee](https://ip.net.coffee/claude/) 的公开接口，评分分段和受限地区规则与其 Claude IP 检测页一致；完整检测页（含 Claude 出口 IP、DNS 与 WebRTC 泄露）请在浏览器里打开该网站查看。
- **出口 IP** 由 Cloudflare 的 `1.1.1.1/cdn-cgi/trace` 返回。
- 两项服务都由第三方提供，CCGuard 只在你点击“检测”时请求它们；服务调整时出口评分会显示“检测失败”，不影响本机监测。
- 安装版界面字体为思源黑体（[Noto Sans SC](https://fonts.google.com/noto/specimen/Noto+Sans+SC)，Adobe 与 Google 发布，SIL Open Font License 1.1），构建时从 [google/fonts](https://github.com/google/fonts/tree/main/ofl/notosanssc) 的固定提交下载并校验哈希，许可文本随程序附带（安装目录 `_internal\claude-guardian\assets\monitor\fonts\OFL.txt`）。
- 安装向导的简体中文翻译来自 Inno Setup 官方仓库收录的社区翻译（[jrsoftware/issrc](https://github.com/jrsoftware/issrc) 的 `Files/Languages/Unofficial/ChineseSimplified.isl`，维护者 Kira），原样保留其署名。
- 项目基于 [Claude-Guardian](https://github.com/DUNHKpcc/Claude-Guardian) 维护。

## 许可

代码采用 **GPL-3.0-only**，见 [LICENSE](LICENSE)。来源原文保留其既有署名与许可声明。CCGuard 与 Anthropic 无隶属关系，也不提供任何免封保证。
