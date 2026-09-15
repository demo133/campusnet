---
name: campusnet
description: 校园网 Portal 自动登录与断网排障（Dr.COM 城市热点 / 深澜 Srun / 锐捷 Ruijie / 华为 eportal）。当用户需要登录校园网、开机后连不上网、需要手动打开认证页、宿舍路由器（OpenWrt）上的定时认证任务突然失效、登录前要先选运营商、想确认自己学校用哪种认证系统，或要在桌面端/路由器上配置自动重连时使用。触发词：校园网、登录校园网、校园网认证、认证页、上网登录页、连不上网、断网了、没网、自动重连、开机没网、重启后没网、Dr.COM、城市热点、深澜、Srun、锐捷、eportal、portal 认证、OpenWrt 认证、路由器认证、校园网失效、校园网自动登录、运营商选择、校园宽带、宿舍路由器。
---

# campusnet —— 校园网自动登录与排障

## 这个 skill 解决什么

把"登录校园网"这件反复发生的事变成一条命令，并覆盖最麻烦的那部分：
**本来能自动登录，突然不行了，怎么查。**

底层是一个零依赖的命令行工具 `campusnet`（纯 Python 标准库，不需要任何第三方包）。
本 skill 负责**判断场景 → 选对命令 → 按症状定位**，而不是让用户去读源码。

> **前置条件**：用户机器上需要能运行 `python3`。
> 下面第 1 步会确认工具是否已装好；装不上的情况也有替代方案，见该节末尾。

## 依赖与权限说明

《Skill 上传规范》要求把"它会做什么、需要什么、不做什么"说清楚，这里集中列一遍。

### 需要什么

- 一个 `python3` 运行时（3.8+）。**不需要任何第三方包** —— 只用标准库。
- 一个命令行工具 `campusnet`（MIT 开源，源码在 GitHub 上可查）：
  `pip install git+https://github.com/demo133/campusnet.git`。
  装不上时用包内说明的零依赖纯 shell 版。
- 用户的校园网账号和密码。**密码只用于向学校的认证门户提交认证，
  不会被写入任何会被分享或提交的文件。** 推荐用环境变量传入、不落盘。

### 它会读取什么

- 本机网络状态（默认网关、当前 Wi-Fi 名称、本机 IP / MAC）——
  用来判断"是否需要认证"以及"该连哪个 Wi-Fi"。
- 用户自己提供的配置文件和账号密码。
- 向**学校的内网认证门户**发 HTTP 请求（通常是内网 IP，走 `http://`）。

### 它不会做什么

- **不收集、不上传**任何与本机及校园网认证无关的数据；没有任何遥测或回传。
- 不申请超出上述范围的权限。
- **不含任何自动操作社交平台账号的能力**（自动发帖、自动回复评论那一类，
  平台明令禁止）。
- 不擅自修改系统设置。只有用户显式执行 `autostart install` 时，
  才会写用户级的开机自启项（Windows 注册表 `Run` / macOS LaunchAgent /
  Linux systemd 用户服务；路由器上是 `/etc/init.d` + cron）。
  `autostart uninstall` 会把自己写的东西删干净。

### 包内附带的可选脚本

不执行也不影响主流程，源码可直接查看：

- `scripts/run.py` —— 定位可用的 campusnet 并调用，省去自己拼 `PYTHONPATH`；
- `scripts/fingerprint.py` —— 生成脱敏报告，脱敏规则见
  `references/helper-scripts.md`。

### 已知边界（如实说明）

`srun` / `ruijie` / `eportal` 三条认证路径**没有真机验证**，只有 `drcom` 实测过。

## 先判断属于哪种场景

| 用户说的话 | 实际属于 | 走哪节 |
| --- | --- | --- |
| "帮我登录校园网" / "连不上网" | 首次配置或临时登录 | 1→4 |
| "每次重启都要手动登录" / "想自动" | 装开机自启 | 5 |
| "路由器上本来好好的，最近失效了" | **排障**（最常见） | 6 |
| "我们学校要选运营商" | 运营商配置 | 3 |
| "换个 Wi-Fi 之后开机连不回校园网" | Wi-Fi 管理 | 5 |
| "开机要等很久才连上" / "偶尔一直连不上" | **开机抢网时机问题** | 5 + `references/troubleshooting.md` B6 |
| "不知道我们学校是哪种认证" | 指纹识别 | 2 |

**不要跳过第 2 步的探测直接猜门户地址和参数。** 各校差异极大，
猜出来的参数会编出一套看起来合理但完全不工作的配置。

## 1. 确认工具可用

```sh
python3 -m campusnet --version
```

提示"没有名为 campusnet 的模块"就先装（两选一）：

```sh
pip install git+https://github.com/demo133/campusnet.git
# 或
git clone https://github.com/demo133/campusnet.git && cd campusnet
```

要求 Python 3.8+，**无第三方依赖**。

**装不上的机器**（例如 flash 很小的路由器）：跳过整个流程，
用纯 shell 版，零依赖、只用系统自带的 `uclient-fetch` 或 `curl`：

```sh
scp community/openwrt/campusnet-openwrt.sh root@192.168.1.1:/usr/bin/
chmod +x /usr/bin/campusnet-openwrt.sh
```

## 2. 探测认证系统与门户（必做）

```sh
python3 -m campusnet detect --verbose
```

输出会给出：认证系统类型、门户地址、页面标题、识别到的参数。
把这个输出当作后续配置的依据。

- 探测失败或识别不出 → 读 `references/fingerprinting.md`
- 已经知道门户地址、只想改一处 → 加 `--portal 地址` 跳过自动探测

## 3. 生成配置

优先走交互式向导（它会把这些都问一遍）：

```sh
python3 -m campusnet setup
```

向导里**「校园 Wi-Fi 名称」这一项一定要填** —— 它是"换过 Wi-Fi 后
开机连不回校园网"的修复前提。

需要手写配置时（例如在路由器上），配置文件是 JSON：

```json
{
  "username": "学号",
  "provider": "auto",
  "portal_ip": "10.99.0.1",
  "wifi_ssid": "校园 Wi-Fi 名称",
  "options": { "carrier": "campus" }
}
```

**密码不要写进配置文件。** 用环境变量 `CAMPUSNET_PASSWORD` 提供；
只有确实需要"无人值守且拿不到环境变量"时，才用 `--save-password`
写入配置并 `chmod 600`。

### 登录前要先选运营商

```sh
python3 -m campusnet carrier              # 看当前设置
python3 -m campusnet carrier 移动          # 持久设置
python3 -m campusnet once --carrier 电信    # 只这一次
```

**必须讲清楚一个区别**：「校园电信 / 校园联通」和「电信 / 联通」
在 Dr.COM 上是**不同的服务类型**（走不同的 `R1`/`R3` 参数），
不是"加不加账号后缀"的区别。用户说不清时，让他看登录页的
服务类型下拉框有哪几个选项。

认不出的运营商不会报错，会被当作账号后缀透传（如 `学号@神秘宽带`），
这恰好是很多学校的真实做法。

## 4. 登录并验证

```sh
python3 -m campusnet once --verbose
```

`once` 默认是**安静模式**：已联网时一个字都不输出、退出码 0。
这是刻意设计 —— 它要被 cron 每 5 分钟调用一次，不能把日志刷满。
所以**排障时一定要加 `--verbose`**，否则看不到任何东西。

期望看到 `result:1`（成功）或 `result:2`/`3`（已在线，也算成功）。

## 5. 装成自动

### 桌面端（Windows / macOS / Linux）

```sh
python3 -m campusnet autostart install
python3 -m campusnet autostart status    # 确认装好了
```

顺序很重要：**必须先能连上校园网，再谈自动认证**。
桌面端"换过 Wi-Fi 后开机连不回校园网"的根因就是这个顺序 ——
程序原先只问"有没有网"，手机热点也有网，于是判定"无需认证"，
Wi-Fi 从头到尾没被碰过。现在这样修：

```sh
python3 -m campusnet wifi status
python3 -m campusnet wifi set <校园Wi-Fi名>
```

### 路由器（OpenWrt）

**不要在路由器上用 `watch` 常驻守护**（白占内存），正确做法是 5 分钟一次 cron：

```sh
python3 -m campusnet autostart install --interval 5 --config /etc/campusnet/config.json
```

它会做三件事，**缺一不可**：写 `/etc/init.d/campusnet`（procd）、
写 `/etc/crontabs/root` 条目、启用并重启 cron 服务。
只做了第一件就以为装好了，是极常见的误判。

配置**必须放在 `/etc/campusnet/`，绝不能放 `/tmp`** ——
`/tmp` 是 tmpfs，重启即清空。

## 6. 排障（"本来好好的，突然失效了"）

**第一步永远是先跑体检，不要凭猜测改配置：**

```sh
python3 -m campusnet doctor
```

它逐项检查并给出可以直接粘的修复命令。有 `✘` 就照着改。

体检没定位到时，读 `references/troubleshooting.md` —— 按**症状**查，
覆盖七类最常见故障：门户地址变了、运营商变了、配置在 `/tmp`、
cron 服务被关、cron 环境取不到密码、WAN 口 MAC/IP 变了、
固件升级没保留配置。

平台相关的路径、自启位置、日志命令见 `references/platforms.md`。

### 一条最省时间的判断

请求**通了但认证失败** → 网络和门户都正常，问题在账号或参数。
请求**本身就不通** → 是网络层问题，不是 campusnet 的问题，别再改配置了。

## 边界（不要越界）

- **不要编造**门户地址、`R1`/`R3`/`para` 取值。这些只能来自 `detect` 或用户实测。
- **不要把密码写进任何会被提交的文件**，也不要在回复里回显用户密码。
- 路由器上 `wifi` 系列命令**不适用**（路由器是上行设备，不是要切网的客户端）。
- `srun` / `ruijie` / `eportal` 三条路径**没有真机验证**，只有 `drcom` 实测过。
  用户用这三家失败时，如实说明这一点，不要假装是用户的配置问题。
- HTTPS 门户在路由器上要额外装 `python3-openssl` + `ca-bundle`；
  内网门户绝大多数是 HTTP，一般用不上。

## 把结果反馈回来（重要）

这个项目最需要的是**不同学校的真实指纹**，而不是更多功能。
用户跑通或卡住时，把下面三样收齐：

1. `python3 -m campusnet detect --verbose` 的输出；
2. `python3 -m campusnet doctor` 的输出；
3. 路由器用户再加 `cat /etc/openwrt_release`（型号 + 版本）。

**务必先打码**：账号、IP、MAC、密码。打码规则和一段可直接运行的
脱敏脚本见 `references/helper-scripts.md`。

反馈渠道：GitHub issue（模板见 `.github/ISSUE_TEMPLATE/fingerprint.md`）。
给一所新学校加支持通常就是加一条指纹规则的事。
