# campusnet · 校园网自动登录

> 一条命令搞定校园网 Portal 认证。开机自动登录，断网自动重连。
> **不会命令行？拉到 [图形版](#图形版双击就能用windows)，下载一个 exe 双击就能用。**

[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen.svg)](#为什么零依赖)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](#)
[![GUI](https://img.shields.io/badge/Windows%20%E5%9B%BE%E5%BD%A2%E7%89%88-%E5%8F%8C%E5%87%BB%E5%8D%B3%E7%94%A8-18b47a.svg)](#图形版双击就能用windows)

零依赖 · 跨平台 · 自动识别认证系统 · 支持 Dr.COM / 深澜 / 锐捷 / 新旧版 eportal

**已在真实校园网环境实测通过。** 欢迎其它学校的同学跑 `campusnet detect` 反馈指纹，一起把覆盖面做广。

```console
$ campusnet status
✔ 网络：已联网
• 认证系统：drcom 1.00  Dr.COM 城市热点
• 本机 IP：10.99.0.40
```

## 图形版：双击就能用（Windows）

给完全不想碰命令行的人准备的：**一个约 10 MB 的 exe，免安装、不用装 Python**，
底层和命令行版是同一套核心，连配置文件都是同一份。

**怎么拿到：**

1. 打开 [Releases](../../releases) 页，下载最新的 `campusnet-gui.zip`（也就是
   校园网助手便携版，解压后一个 exe 加一份使用说明）；
2. 解压，双击 `校园网助手.exe`（首次运行如果 Windows 弹蓝色警告，
   点「**更多信息 → 仍要运行**」—— 程序没有做代码签名，只第一次会弹）；
3. 跟着向导填一遍：**学号、密码**（可勾选显示），**运营商**下拉选择，
   **校园 Wi-Fi 名**会自动带上当前连的网，勾上「**开机自动登录**」，
   点「保存并立即连接」—— 保存完它会立刻帮你认证一次。

之后每次开机它自己把网连好；想手动操作时，主界面就几个大按钮：

| 按钮 | 干什么用 |
| --- | --- |
| **立即重新认证** | 网页打不开、认证过期时点一下，重新走一遍登录 |
| **一键体检** | 「本来好好的怎么突然不行了」—— 逐项排查，给人话结论 |
| **账号设置** | 改学号密码、换运营商、改 Wi-Fi 名 |
| **开机自启** | 开关式切换，装/卸开机自动登录 |

几个你可能关心的点：

- **报错全是中文人话**，不会甩你一行 `Connection refused`；
  程序自己崩了这种极端情况也有日志：`%LOCALAPPDATA%\campusnet\gui-errors.log`
- **密码默认存进 Windows 凭据管理器**，配置文件里不留明文（打包版自带 keyring）
- 支持系统：**Windows 10 / 11（64 位）**
- **卸载**：在主界面把「开机自启」关掉，删掉 exe 就行；
  想清干净再删 `%APPDATA%\campusnet` 文件夹（里面没有明文密码）
- 命令行的所有高级玩法（`watch` 参数、`--option` 逃生舱、路由器部署）图形版没有 ——
  那些需求请用下面的命令行版，两者共用一份配置，互不冲突
- 想自己打包：仓库里 `release/build_exe.py` 一键出包（需要能跑 tkinter 的 Python
  和 PyInstaller，脚本内置了两个打包坑的处理）

## 特性

- **图形版** —— Windows 双击即用，不需要 Python 和命令行（见[上文](#图形版双击就能用windows)）
- **自动识别认证系统** —— 探测门户页面做指纹识别，不用你告诉它学校用的哪家
- **换过 Wi-Fi 也能自己连回来** —— 手动切到手机热点后重启，会自动切回校园网
- **支持先选运营商** —— 登录前要挑「移动 / 电信 / 联通」的学校也能用
- **零第三方依赖** —— 只用 Python 标准库，宿舍内网也装得上
- **开机自启** —— Windows 注册表 / macOS LaunchAgent / Linux systemd，无需管理员权限
- **路由器也能跑** —— OpenWrt 上走 procd + 5 分钟 cron，还带一个不依赖 Python 的纯 shell 版
- **守护模式** —— 定时检查，夜间断网、早上恢复后自动重新认证
- **一键体检** —— `campusnet doctor` 逐项排查「本来好好的怎么突然失效了」
- **不打扰** —— 已联网时直接退出，不发多余请求
- **凭据安全** —— 优先环境变量 / 系统钥匙串，明文落盘需显式同意

## 安装

> **没有 Python、不想敲命令？** 直接看上面[图形版](#图形版双击就能用windows)，
> 下载 exe 就能用，下面的内容都可以跳过。

```bash
pip install git+https://github.com/demo133/campusnet.git
```

或克隆后直接用，无需安装：

```bash
git clone https://github.com/demo133/campusnet.git
cd campusnet && python -m campusnet status
```

要求 Python 3.8+，无第三方依赖。

> **在路由器上跑？** 先看 [docs/openwrt.md](docs/openwrt.md) —— 那是另一套用法
> （不是常驻守护，而是 procd + 5 分钟 cron），排障清单也在那里。

> **想用自然语言驱动它？** 仓库里带了一个 skill（`skill/campusnet/`），
> 放进技能目录后，直接把"我校园网连不上""路由器上以前能自动登录最近失效了"
> 说出来就行。见 [docs/skill.md](docs/skill.md)。

## 快速开始

```bash
campusnet setup               # 1. 生成配置（交互式，自动探测认证方式）
campusnet login               # 2. 登录一次试试
campusnet autostart install   # 3. 装成开机自启
```

> **第 1 步里问的「校园 Wi-Fi 名称」一定要填。** 它修的是下面这个问题。

## 换过 Wi-Fi 之后开机连不回校园网？

这是校园网自动登录最常见的翻车点，因为它的成因有点反直觉：

1. 你把 Wi-Fi 从校园网手动换成手机热点（或者别人的热点）；
2. 关机再开机，系统发现热点也有「自动连接」，就先连上热点了；
3. 热点能上网 → 联网探测通过 → 自动登录逻辑认为「已联网，无需认证」，
   于是**根本不会去碰 Wi-Fi**。

结果就是一直挂在热点上，校园网永远连不上 —— 明明有网，却不是你要的那个网。

**关键在于判断依据**：不能问「有没有网」，而要问「连的是不是校园网」。
所以 `campusnet` 在联网探测**之前**会先确认 Wi-Fi：

```bash
campusnet wifi set CampusWiFi          # 记住校园网名称（填你自己的 SSID）
campusnet wifi autoconnect      # 关闭其它网络自动连接（治本）
campusnet wifi                  # 看当前 Wi-Fi 状态
```

三条命令各自的作用：

| 命令 | 作用 | 是否必须 |
| --- | --- | --- |
| `wifi set <名称>` | 记下校园网 SSID，之后登录前会检查 | **必须**，不填就没有切网功能 |
| `wifi autoconnect` | 把其它所有 Wi-Fi 改成「手动连接」，开机时系统就没得抢 | 强烈建议 |
| `wifi` | 诊断：当前连的哪个网、是否在目标上、保存了哪些网络 | 排查用 |

只做第一步也能修好：每次登录前如果发现连的不是校园网，会执行
`netsh wlan connect` 并等它真的连上（最多 30 秒）再走认证流程。
第二步是**治本** —— 让开机时压根不会去连别的网。

配置好之后的行为：

```console
$ campusnet login
! 当前 Wi-Fi 是「iPhone 热点」，需要切回校园网「CampusWiFi」…
✔ 已连接到 Wi-Fi「CampusWiFi」
✔ 认证成功，网络已连通
```

再也不用先手动切回校园网了。`watch` 守护模式每一轮也会做这个检查，
所以用着用着 Wi-Fi 被切走，下一个周期就会被拉回来。

> macOS 没有「关闭单个网络自动加入」的接口，`wifi autoconnect` 是空操作；
> 但 `wifi set` + 登录前自动切网在三个平台上都有效。

## 开机那一下连不上校园网？

上面说的是「连到了别的网」。还有一种更像玄学的情况：

**开机后压根没连上，过一会儿又自己好了；偶尔一直不好，得手动点一下。**

原因不在认证，在**时机** —— 守护进程是登录时启动的，而这一刻无线驱动、
Windows 的 `WlanSvc`、校园网的 SSID 广播往往还要再过十几秒才准备好。
这期间发连接命令必然失败，而旧逻辑失败一次就要等满一个检查周期（默认 10 分钟），
体感就是"开机一直没网"。

所以 `watch` 分成了两个阶段：

| 阶段 | 行为 |
| --- | --- |
| **开机热身** | 开头 180 秒内每 15 秒重试一次（等网卡 → 切网 → 登录整条走一遍），一连上立刻转入常规 |
| **常规守护** | 联网正常就按 `--interval` 检查；哪一轮没弄通，用 60 秒快速重试，不干等十分钟 |

```bash
campusnet watch --warmup 180 --warmup-gap 15 --retry-gap 60   # 这就是默认值
```

**装好自启的用户不用改任何东西**，这些是默认值，重启后直接生效。
想关掉热身用 `--warmup 0`；想把重试调得更凶用
`campusnet watch --option wifi_attempts=3 --option wifi_ready_timeout=40`。

配合上面的 `wifi autoconnect` 一起用效果最好：既不会连错网，
也不会因为"连得太早"而白失败一次。

## 登录前要先选运营商？

**可以，加一条命令就行。**

有些学校的校园网登录页不只是填账号密码，还得先从「校园用户 / 中国移动 /
中国电信 / 中国联通」里面选一个 —— 不选就认证失败，或者选错了上不了外网。

`campusnet` 支持这个。设一次，之后 `login` / `watch` 都会自动带上：

```bash
campusnet carrier 移动        # 设成中国移动
campusnet carrier             # 看看现在设的是什么
campusnet login               # 正常登录
```

向导里也会问（`campusnet setup` 的第 4 步），
临时改一次可以用 `campusnet login --carrier 电信`。

各认证系统是怎么表达运营商的：

| 认证系统 | 实现方式 |
| --- | --- |
| Dr.COM 城市热点 | 用隐藏字段 `R1` / `R3` / `para`，部分学校再加账号后缀（`@cmcc`） |
| 深澜 Srun | 用 `domain` 参数（`domain=cmcc`），或账号后缀 |
| 锐捷 / eportal | 一般没有独立字段，运营商直接拼在账号后缀上 |

能填的值（中文、英文、大小写都认）：

| 你说 | 归一成 | Dr.COM 参数 | 账号后缀 |
| --- | --- | --- | --- |
| 校园用户 / 校园网 / 默认 | `campus` | `R1=0 R3=0 para=00` | — |
| 移动 / 中国移动 / CMCC | `cmcc` | `R1=0 R3=0 para=30` | `@cmcc` |
| 电信 / 中国电信 | `telecom` | `R1=0 R3=0 para=00` | `@telecom` |
| 联通 / 中国联通 | `unicom` | `R1=0 R3=0 para=00` | `@unicom` |
| 校园其他 / 其它 | `other` | `R1=0 R3=0 para=30` | — |
| 校园电信（Dr.COM 独立选项） | `campus_telecom` | **`R1=1`** R3=0 para=00 | — |
| 校园联通（Dr.COM 独立选项） | `campus_unicom` | R1=0 **`R3=1`** para=00 | — |

> ⚠️ **别把「校园电信」和「电信」搞混。** 这两个在 Dr.COM 上是**不同的服务类型**：
> 「校园电信」走 `R1=1`，「电信」只是给账号加个 `@telecom` 后缀。
> 填错了参数发出去就是认证失败，而且报错信息看不出来。学校页面上写的是哪个就填哪个。

**认不出的名字不会被拒**。如果你学校的运营商不在上面，直接填它的名字就行 ——
`campusnet` 会把它当账号后缀用（`campusnet carrier 某某宽带` → 账号变成
`学号@某某宽带`），这恰好是很多学校的做法。实在不对还能用逃生舱直接写死参数：

```bash
campusnet login --option r1=1 --option r3=0 --option para=00
```

`--option k=v` 可以重复，值会原样传给认证接口（除 `true`/`false` 外都当字符串，
所以 `para=00` 不会被吃成 `para=0`）。它也能盖过 `--carrier` 之类的语义化开关，
还可以写进配置：

```json
{ "options": { "r1": "1", "r3": "0", "para": "00" } }
```

> **不选运营商、也没设 `carrier` 会怎样？**
> 默认按「校园用户」走（`R1=0 R3=0 para=00`，不加后缀）。
> 如果你的学校本来就不需要选，这就是对的；需要选的话认证会失败，
> 设一下 `campusnet carrier` 即可。

## 突然不自动登录了？

这是校园网工具最常见的问题，而且**症状永远都是「本来跑得好好的，最近突然失效」**。
与其猜，不如先跑一次体检：

```bash
campusnet doctor
```

它会逐项检查下面这些，并给出可以照着做的修复建议：

| 检查项 | 失效时通常意味着什么 |
| --- | --- |
| 网络 | 压根没连上校园网，或者 DHCP 没拿到 IP |
| 门户 | **学校改了登录页地址或接口**（最高频） |
| 账号 | 有账号但取不到密码 —— 定时任务里尤其容易踩 |
| 运营商 | 套餐变了 / 后缀不对，报错还看不出原因 |
| 自启 | 定时任务没装，或者装了没启用 |
| 定时任务 | 条目在但 `crond` 没跑；文件放在 `/tmp` 里被清掉了 |
| 配置位置 | **配置写在 `/tmp`**，重启/升级就没了 |

`doctor` 还会顺手把一条**不依赖本工具**的原始认证命令拼好给你
（`uclient-fetch` / `curl` 直接打接口），这样能一刀切开"是网络问题还是程序问题"。

路由器用户的完整排查清单见 [docs/openwrt.md](docs/openwrt.md#四本来好好的最近突然失效了排查清单)。

## 命令

| 命令 | 作用 |
| --- | --- |
| `setup` | 交互式生成配置 |
| `detect` | 探测门户并做指纹识别 |
| `login` | 登录一次（已联网则跳过，`--force` 强制重登） |
| `once` | 跑一次就走，**给 cron / 路由器用**（已联网时零输出） |
| `watch` | 常驻守护，定时检查并自动补登录（开机头 180 秒会密集重试，专治"刚开机连不上"） |
| `doctor` | 逐项体检，排查「突然失效了」 |
| `wifi [status\|list\|connect\|autoconnect\|set\|restore]` | 查看/管理 Wi-Fi，解决换网后连不回校园网 |
| `carrier [值]` | 查看/设置运营商，登录前要选服务类型的学校用 |
| `status` | 查看联网状态与本机信息（加 `--check` 则未联网时返回非零，方便写进脚本） |
| `providers` | 列出支持的认证系统 |
| `autostart install\|uninstall\|status` | 管理开机自启（OpenWrt 上走 procd + cron） |

常用参数：`--config` 指定配置 · `--provider` 强制认证方式 · `--portal` 指定门户 ·
`--interval` 守护间隔 · `--warmup` / `--warmup-gap` / `--retry-gap` 调开机热身与重试节奏 ·
`--wifi` 临时指定校园网 · `--carrier` 临时指定运营商 ·
`--option k=v` 直接写 provider 参数 · `--verbose` 打印请求细节

## 支持的认证系统

| Provider | 认证系统 | 状态 |
| --- | --- | --- |
| `drcom` | Dr.COM 城市热点 | ✅ **某高校**实测 |
| `srun` | 深澜 Srun | 已实现，待验证 |
| `ruijie` | 锐捷 Ruijie | 已实现，待验证 |
| `eportal` | 华为 / 通用 eportal | 已实现，待验证 |
| `eportal_portal` | 新版 eportal（`portal/login` JSONP 接口） | 已实现，待验证 |
| `custom` | 自定义模板 | ✅ |
| `auto` | 自动探测（默认） | ✅ |

没在上面？跑 `campusnet detect` 把指纹发到 issue，或用 `custom` 自己填接口。
协议细节和开发指引见 [docs/providers.md](docs/providers.md)。

## 平台

| 平台 | 开机自启怎么做的 | 备注 |
| --- | --- | --- |
| Windows | 注册表 `HKCU\...\Run` | 用 `pythonw.exe`，不弹黑框；或直接用[图形版](#图形版双击就能用windows) |
| macOS | `~/Library/LaunchAgents/com.campusnet.watch.plist` | `KeepAlive` 挂了自动拉起 |
| Linux | systemd 用户服务；没有 systemd 时退回 `crontab @reboot` | 不需要 root |
| **OpenWrt** | **procd init 脚本 + `/etc/crontabs/root` 每 5 分钟一次** | 见 [docs/openwrt.md](docs/openwrt.md) |
| Docker / 树莓派 | — | [计划中](CHANGELOG.md) |

**路由器是个例外**，值得单独说：OpenWrt 上不适合跑常驻守护（flash 和内存都紧），
所以 `autostart install` 在那里写的是 **procd + cron**。
另外路由器扮演的是**上行设备**而不是客户端，所以 `wifi` 子命令在它上面**不适用** ——
`campusnet wifi` 会直接把该用的 `uci` 命令告诉你，而不是假装去切网。

flash 小到装不下 Python 的机器，用
[`community/openwrt/campusnet-openwrt.sh`](community/openwrt/) —— 纯 busybox sh，零依赖。

## 配置

| 平台 | 路径 |
| --- | --- |
| Windows | `%APPDATA%\campusnet\config.json` |
| macOS / Linux | `~/.config/campusnet/config.json` |

> 图形版用的就是这份配置 —— 命令行配好的，图形版打开就能看到；反过来也一样。

主要字段：

| 字段 | 说明 |
| --- | --- |
| `username` | 学号 / 上网账号 |
| `portal_ip` | 认证门户地址，探测到后会自动写入 |
| `wifi_ssid` | **校园 Wi-Fi 名称**，填了才会自动切网（见上文） |
| `provider` | 认证系统，默认 `auto` 自动识别 |
| `timeout` | 单次请求超时（秒） |
| `options.carrier` | 运营商，见[「登录前要先选运营商？」](#登录前要先选运营商) |
| `options.r1` / `r3` / `para` | Dr.COM 逃生舱：直接写死页面上的隐藏字段（也能用 `--option r1=1`） |
| `options.username_suffix` | 强制指定账号后缀（如 `@cmcc`） |
| `options.domain` | Srun 的 `domain` 参数 |
| `options.wifi_timeout` | 登录前等 Wi-Fi 连上的最长秒数，默认 30 |

`options` 里可以放任意键值 —— 它们会原样交给当前 provider。
所以遇到「我们学校还多一个 `R7` 字段」这种特殊情况，不改代码也能对付：

```bash
campusnet login --option R7=1
```

也可以用环境变量，适合不落盘：

```bash
export CAMPUSNET_USERNAME=你的学号
export CAMPUSNET_PASSWORD=你的密码
```

密码存放优先级：环境变量 → 系统钥匙串（装了 `keyring`）→ 配置文件 → 交互输入。
只有加 `--save-password` 才会明文写进配置文件。

## 常见问题

**图形版和命令行版是什么关系？**
同一套核心、同一份配置文件。图形版是把"配一次 + 日常点两下"做成了窗口；
命令行版的能力更全（`watch` 参数调节、`--option` 逃生舱、`once` + cron、路由器部署）。
两个随便混用，改来改去不会互相覆盖账号以外的设置。

**双击图形版弹出「Windows 已保护你的电脑」？**
程序没做代码签名，SmartScreen 的正常提示。点「更多信息 → 仍要运行」，
只第一次会弹。介意的同学可以自己用 `release/build_exe.py` 从源码打包。

**解压后只看到说明文件，找不到 exe？**
多半是杀毒软件把没签名的 exe 静默拦了。打开「Windows 安全中心 → 病毒和
威胁防护 → 保护历史记录」（360 / 电脑管家在"恢复区"），恢复并允许，
再重新解压即可。

**图形版怎么卸载？**
主界面把「开机自启」关掉，删掉 exe 即可；想彻底清理再删配置目录
（Windows 是 `%APPDATA%\campusnet`），里面没有明文密码。

**会不会反复失败把账号锁了？**
不会。命中即停，每次先探测是否已联网，已联网直接退出；`auto` 模式单次最多试 3 个 provider。

**认不出我们学校怎么办？**
跑 `detect`，把输出（**记得给账号、IP、MAC 打码**）发到 issue，通常加一条指纹规则就能支持。

**开机后连到别的 Wi-Fi 就不回校园网了？**
填上 `wifi_ssid`（`campusnet wifi set 你的SSID`）。原因和原理见上文
[「换过 Wi-Fi 之后开机连不回校园网」](#换过-wi-fi-之后开机连不回校园网)。

**我们学校登录还要先选运营商，能用吗？**
能。`campusnet carrier 移动`（或 `电信` / `联通` / `校园用户`）设一次就行，
细节见[「登录前要先选运营商？」](#登录前要先选运营商)。

**本来每天自动登录，最近突然不行了？**
跑 `campusnet doctor`。它会逐项检查门户地址、账号密码、运营商、定时任务、
配置是否在易失目录，并给出修复建议。见[「突然不自动登录了？」](#突然不自动登录了)。

**能不能装在路由器上（OpenWrt / 宿舍路由器）？**
能。`campusnet autostart install --interval 5` 会在 OpenWrt 上写 procd 脚本
加一条 5 分钟的 cron。完整步骤和排障清单见 [docs/openwrt.md](docs/openwrt.md)。
装不上 Python 的老路由器可以用那个纯 shell 版本。

**cron 里能跑吗？**
能，用 `campusnet once`（不是 `login`）：已联网时**一个字都不输出**、
退出码 0；真没连上才打日志并非零退出 —— 这样 cron 不会刷日志，
出了问题又刚好会给你发信。

**为什么零依赖、不模拟浏览器？**
能直连接口就绝不模拟浏览器——快、稳、日志清晰、不用下载 Chromium。标准库够用，就不引第三方包。

**安全吗？**
请求只发往你学校的认证服务器，无第三方中转；密码默认不落盘；代码量小，可自行审阅。

## 参与贡献

最缺的是**更多学校的指纹样本**。跑 `campusnet detect --verbose` → 开 issue（标题 `[指纹] 学校名 · 认证系统`），
或直接提 PR 加一个 provider。

## 更新日志

见 [CHANGELOG.md](CHANGELOG.md)。发布说明见 [docs/releases/](docs/releases/)，
上手发布流程见 [docs/PUBLISHING.md](docs/PUBLISHING.md)。

## License

[MIT](LICENSE)
