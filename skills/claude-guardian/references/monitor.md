# 实时监测与通知（本机只读面板）

2026-11-14。面向已完成防护部署的本机：给出一个实时状态面板，并在关键检查项失效时用页面通知或系统气泡提醒。

## 用途与边界

- **只读**：不修改防火墙、不重启代理核心、不改任何配置，不调用 `Set-*`。
- **不联网**：不发起任何出站请求，因此不属于联网探测，也不触发接触门禁。
- **不需要管理员**：以普通用户运行；提权只在执行开关操作时由 `killswitch.py` 单独请求。
- **不替代验收**：监测通过只表示本机状态与配置符合预期，不代表出口、DNS、账号或平台验收已通过。
- **v1 只支持 Windows**；macOS 与 Linux 的采集返回未知，界面仍可打开但所有项显示 `unknown`。

## 支持范围

| 项目 | 说明 |
| --- | --- |
| 系统 | Windows 10/11，PowerShell 5.1 |
| 代理客户端 | FlClash、Clash Verge Rev、Clash Nyanpasu、Clash for Windows、Mihomo / Clash.Meta、sing-box、Hiddify、v2rayN、NekoRay / NekoBox；也可自定义进程名与 TUN 名称片段 |
| Python | 3.10+，只用标准库 |
| 依赖服务 | 无；不安装服务、不建计划任务、不写开机自启 |
| 界面 | 独立 tkinter 窗口（默认）或本地网页（备选）；两者都不需要浏览器即可收到通知 |
| 字体 | 读取仓库 `fonts/` 及其子文件夹里用户自备的 .ttf/.otf（进程内私有注册，不安装到系统），按字体文件内的真实字体名选用：正文优先 Anthropic Sans Text（静态字重），其次 Anthropic Sans Web Text；标题 Anthropic Serif；代码 Anthropic Mono。中文由系统字体自动补字；文件缺失时回退微软雅黑／Georgia／Consolas。`fonts/` 已列入 `.gitignore`，字体不随仓库或安装包分发 |
| 采集方式 | 单次 PowerShell 查询，返回进程、网卡、路由、防火墙、DNS 与 IPv6 绑定 |
| 采集间隔 | 默认 5 秒，配置项 `alerts.interval_seconds` |

## 客户端预设与自动识别

`proxy.client` 可选内置预设，预设会自动填入进程名、TUN 名称片段和配置格式；`process_names`、`tun_adapter`、`config_format` 仍可在配置里覆盖。不填 `client` 时按 `process_names` 或已知核心名自动匹配。

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

- **TUN 自动识别**：`tun_adapter` 默认 `auto`，按网卡名称和描述里的片段匹配。客户端改网卡名后通常不用改配置；名称完全对不上时用 `tun_match` 加一个片段。
- **进程名**：`process_names` 不填时使用预设；显式填写优先于预设；`client` 与 `process_names` 都不填时，任一已知代理核心在运行就算通过。
- **配置格式**：`config_format` 默认 `auto`。`.yaml`/`.yml` 按 Clash/Mihomo 解析；`.json` 按顶层键区分 sing-box（`route`、`tun` 或 `inbounds[].type`）与 Xray（`routing`）。也可以强制指定 `clash`、`sing-box`、`xray`。
- **运行配置路径**：必须填客户端实际加载的那一份。不同客户端和版本的路径不同，这里不猜；填 `""` 可关闭三项配置检查。常见位置如下，仍以客户端当前设置为准。

| 客户端 | 常见运行配置位置（示例，需自行确认） |
| --- | --- |
| FlClash | `%APPDATA%\com.follow\clash\config.yaml` |
| Clash Verge Rev | `%APPDATA%\io.github.clash-verge-rev.clash-verge-rev\` 下当前 profile 生成的运行配置 |
| Clash Nyanpasu | `%APPDATA%\io.github.clash-nyanpasu.clash-nyanpasu\` 下当前 profile |
| sing-box | 客户端设置里显示的实际配置文件（`config.json`） |
| Hiddify | 客户端生成的 `config.json`（以界面显示的路径为准） |
| v2rayN | 客户端生成的 `config.json`（以界面显示的路径为准） |
| NekoRay / NekoBox | `%APPDATA%\nekoray\config\config.json` 或客户端当前 profile |

不同格式能表达的项目不同：Clash/Mihomo 能读 `ipv6`、`tun.enable`、`tun.strict-route`、`dns-hijack`；sing-box 能读 `tun`／`inbounds[type=tun]` 的 `enable`、`strict_route`、`inet4/inet6_address` 或 1.11+ 的 `address` 列表，以及 `route.rules` 的 `hijack-dns`；Xray 能读 `dns.queryStrategy`、`routing.domainStrategy` 和 `sniffing.destOverride` 里的 `dns`。读不出的项显示 `unknown`，不按通过处理。

## 首次配置

1. 确认已完成防护部署：默认出站 Block、`guardian-*` 规则存在、TUN 正常。
2. 把 `assets/monitor/config.example.json` 复制到本机私有目录。
3. `target` 填 `python -c "import platform; print(platform.node())"` 的精确输出。
4. `proxy.client` 填上表里的预设；TUN 名称不确定就保持 `auto`。
5. `proxy.runtime_config` 填客户端实际加载的运行配置绝对路径；不想检查配置项就留空。
6. `proxy.process_names` 可省略（用预设）或填核心进程名；`proxy.tun_match` 只在自动识别不到时补充。
7. 不填写任何订阅、节点、密码或令牌；配置里没有这些字段。

## 启动与入口

```sh
python scripts/monitor.py detect                                        # 只读列出候选核心与 TUN 网卡（不需要配置）
python scripts/monitor.py check  --config <private>/monitor.json          # 单次采集，输出 JSON
python scripts/monitor.py gui    --config <private>/monitor.json --tray   # 独立窗口 + 托盘（默认入口）
python scripts/monitor.py serve  --config <private>/monitor.json          # 本地网页（备选）
python scripts/monitor.py desktop --config <private>/monitor.json --output <新目录>
python scripts/monitor.py register-notifier --config <private>/monitor.json   # 可选：通知以 CCGuard 署名（在开始菜单建一个入口）
python scripts/monitor.py unregister-notifier     # 撤销上一项
python scripts/monitor.py notifier-status         # 查看是否已注册
```

- **候选识别**（`detect`）：不需要配置，只读列出正在运行的已知代理核心、候选 TUN 网卡（名称／描述／状态）和可能的 `client` 预设，用来填写首次配置；只在 Windows 上可用，不联网。
- **通知名称**：Windows 按发送程序给通知署名，托盘运行在 PowerShell 里，所以默认显示「Windows PowerShell」。未打包的程序要用自己的名字，必须有一个带程序身份（`System.AppUserModel.ID` = `CCGuard.Monitor`）的开始菜单快捷方式；只写注册表的身份会被 Windows 静默丢弃（Windows 11 26300 实测）。`register-notifier` 只在当前用户的开始菜单目录（`%APPDATA%\Microsoft\Windows\Start Menu\Programs\CCGuard.lnk`）创建这一个快捷方式，不需要管理员；它同时是启动面板的入口。同名快捷方式不属于 CCGuard 时拒绝覆盖。`unregister-notifier` 只删除带本程序身份的这一个快捷方式。托盘只在快捷方式存在、且系统里 CCGuard 的通知未被关闭时发 Toast（首次发送前系统报告的开关值为空，按未关闭处理）；被关闭或系统通知接口不可用时回退为气泡，告警不丢。重启托盘后生效；移动程序目录或配置后需重新注册。需要用户确认后再执行注册。

- **独立窗口**（`gui`）：tkinter 原生面板，分「状态 / 日志 / 设置」三页；托盘负责系统气泡通知，不需要浏览器。窗口图标与托盘图标是按整体状态换色的盾牌，内含白色符号，色弱时也能区分：绿 ✓ 正常、橙 ! 降级、红 ✕ 失效、灰 — 未知。
- **关闭窗口**会先询问：隐藏到托盘（监测与托盘提醒继续）或直接关闭（停止监测）；取消则保持打开。未启动托盘时只提供关闭或取消。隐藏后双击托盘，或用托盘菜单「打开面板」，即可恢复窗口。
- **网页备选**（`serve`）：只监听 `127.0.0.1` 的随机端口，路径带随机会话令牌，并校验 `Host`、`Origin`、`Sec-Fetch-Site`，带严格 CSP。
- `--idle-minutes` 只作用于 `serve`（默认 15 分钟无访问自动退出；`0` 表示不自动退出）。
- `desktop` 生成 `.lnk`／`.app`／`.desktop`，不写自启项；入口固定带 `--tray`，关掉页面后托盘继续提醒。移动程序目录或配置后需要重新生成。

## 检查项与判定

| ID | 检查 | 失败时 |
| --- | --- | --- |
| `proxy_core` | 配置的进程名、客户端预设或已知代理核心是否在运行 | `fail` |
| `tun_adapter` | 配置的 TUN 网卡或自动识别到的 TUN 存在且 Up | `fail` |
| `default_route` | `0.0.0.0/0` 最低度量路由的接口是否为 TUN | `fail` |
| `firewall_block` | 三档防火墙启用且默认出站为 Block | `fail` |
| `guardian_rules` | 启用的放行规则数量是否达到配置下限 | `degraded` |
| `core_ipv6` | 运行配置是否关闭 IPv6（按 Clash／sing-box／Xray 分别解析） | `degraded` |
| `strict_route` | 运行配置是否开严格路由（Clash `tun.strict-route`、sing-box `strict_route`） | `degraded` |
| `dns_hijack` | 运行配置是否接管 53 端口 DNS（Clash `dns-hijack`、sing-box `hijack-dns`、Xray DNS sniffing） | `degraded` |
| `dns_servers` | 物理网卡 DNS 等于期望值 | `degraded` |
| `os_ipv6` | 物理网卡 IPv6 绑定已禁用 | `degraded` |

`overall`：任一 `fail` → `fail`；否则任一 `degraded` → `degraded`；全部 `ok` → `ok`；其余 → `unknown`。查询失败、权限不足或数据缺失一律记 `unknown`，不推测为通过。

`core_ipv6`、`strict_route`、`dns_hijack` 是尽力而为的映射：所选格式无法表达、键名版本不同或配置留空时记 `unknown`，需人工核对，不当作通过。

物理网卡按接口描述排除自动识别到的 TUN 以及 `Meta Tunnel`、`sing-tun`、`Mihomo`、`Clash`、VMware、Hyper-V、ZeroTier、Bluetooth、回环等虚拟网卡；只检查状态为 Up 的接口。

## 通知

- **独立窗口**：状态页卡片按圆点颜色区分（绿/橙/红/灰），日志页记录每次状态跃迁和设置变更；设置页可调采集间隔、通知冷却、通知项和暂停提醒。「保存到配置」先完整校验再原子替换文件，校验不过时原配置不动；`alerts.paused` 是可选布尔值。
- **关闭窗口**：用 `--tray` 启动且托盘仍在时，可选隐藏到托盘、直接关闭或取消；没有托盘时只提供关闭或取消，避免窗口隐藏后无法找回。
- **托盘**：`--tray` 启动后常驻，读取监测进程写出的 `state.json`；图标与悬停文字按整体状态换色换字，气泡通知按 `alerts.notify_states` 与冷却时间触发，恢复时也提示。监测超过 3 个采集周期没有更新时显示「监测已停止更新」。
- **暂停**：面板设置里的「暂停提醒」写入状态的 `paused` 字段，托盘同时生效；托盘菜单里的「暂停提醒」只影响本次托盘进程。面板修改的采集间隔与冷却也经 `state.json` 同步给托盘，「已停止更新」按当前间隔判断。
- **网页备选**：点击「开启通知」授权后，检查项状态跃迁时弹出浏览器通知。
- 只报告状态与检查项名称，不含 IP、路径、节点或配置值。
- Windows 专注助手或通知设置可能吞掉气泡；以面板显示为准。

## 故障时怎么办

1. 先看面板哪一项变色，按 ID 对照上面表格。
2. `fail` 项按既有流程处理：核心与 TUN 由客户端恢复；防火墙默认出站被改回 Allow 时按回滚命令恢复。
3. `degraded` 项通常是配置漂移：订阅更新或客户端升级可能改回 DNS 覆写、关闭严格路由或更换配置键名，恢复后重新核对。
4. 核心、TUN 或配置项长期显示 `unknown`：先用 `detect` 核对进程名和网卡名，再检查 `config_format` 与 `runtime_config` 是否指向客户端实际加载的配置。
5. 监测本身不修改任何东西；不要把它当成修复入口。

## 不做的事

- 不创建开机自启、Windows 服务或计划任务。
- 除用户主动执行的 `register-notifier`（当前用户开始菜单里的一个 CCGuard 快捷方式，可用 `unregister-notifier` 撤销）外，不写开始菜单或注册表。
- 不做联网探测、出口 IP 检查、延迟测速或 DNS 泄露测试。
- 不自动重启核心、不改防火墙、不关闭或启用规则。
- 不读取或回显 `proxies`、`proxy-groups`、订阅链接与凭据。
- 不在 macOS/Linux 上冒充已支持。

## 验证与已知限制

- 单元测试覆盖配置校验、客户端预设、TUN 自动识别、Clash／sing-box／Xray 解析、状态机、通知冷却、输出脱敏与 HTTP 鉴权；页面逻辑用 Node 合成测试，不启动浏览器。
- 真机验收：FlClash 上启动面板核对 10 项与实际一致；关闭代理核心后 5–10 秒内出现告警；恢复后收到恢复提示。其他客户端与版本按上表的字段解析，未逐项真机验收。
- 已知限制：托盘依赖 PowerShell 与 WinForms；通知可能被系统专注助手抑制；`unknown` 不等于正常；客户端升级可能改变进程名、TUN 名称或配置键名，自动识别不到时用 `process_names`、`tun_match`、`config_format` 显式指定。
