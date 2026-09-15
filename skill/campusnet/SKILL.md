---
name: campusnet
description: 校园网 Portal 自动登录与断网排障（Dr.COM 城市热点 / 深澜 Srun / 锐捷 Ruijie / 华为 eportal）。当用户需要登录校园网、开机后连不上网、需要手动打开认证页、宿舍路由器（OpenWrt）上的定时认证任务突然失效、登录前要先选运营商、想确认自己学校用哪种认证系统，或要在桌面端/路由器上配置自动重连时使用。触发词：校园网、登录校园网、校园网认证、认证页、上网登录页、连不上网、断网了、没网、自动重连、开机没网、重启后没网、Dr.COM、城市热点、深澜、Srun、锐捷、eportal、portal 认证、OpenWrt 认证、路由器认证、校园网失效、校园网自动登录、运营商选择、校园宽带、宿舍路由器。
---

# campusnet —— 校园网自动登录与排障

## 这个 skill 解决什么

把"登录校园网"这件反复发生的事变成一条命令，并覆盖最麻烦的那部分：
**本来能自动登录，突然不行了，怎么查。**

底层是 `campusnet` 这个零依赖命令行工具（纯 Python 标准库）。
本 skill 负责**判断场景 → 选对命令 → 按症状定位**，而不是让用户去读源码。

## 先判断属于哪种场景

| 用户说的话 | 实际属于 | 走哪节 |
| --- | --- | --- |
| "帮我登录校园网" / "连不上网" | 首次配置或临时登录 | 步骤 1→4 |
| "每次重启都要手动登录" / "想自动" | 装开机自启 | 步骤 5 |
| "路由器上本来好好的，最近失效了" | **排障**（最常见） | 步骤 6 |
| "我们学校要选运营商" | 运营商配置 | 步骤 3 的运营商一节 |
| "换个 Wi-Fi 之后开机连不回校园网" | Wi-Fi 管理 | 步骤 5 的桌面端一节 |
| "开机要等很久才连上" / "偶尔一直连不上" | **开机抢网时机问题** | 步骤 5 的桌面端一节 + `references/troubleshooting.md` B6 |
| "不知道我们学校是哪种认证" | 指纹识别 | 步骤 2 |

**不要跳过步骤 2 的探测直接猜门户地址和参数。** 各校差异极大，
猜出来的参数会编出一套看起来合理但完全不工作的配置。

---

## 步骤 1：确认 campusnet 可用

```sh
python <skill>/scripts/run.py --version
```

`scripts/run.py` 会按顺序找一个可用的 campusnet：已安装的 → 本机 clone 的仓库 → 报错并给出安装命令。
不要自己拼 `PYTHONPATH`，用这个脚本。

若报"未找到 campusnet"，按提示装（二选一）：

```sh
pip install git+https://github.com/demo133/campusnet.git
# 或
git clone https://github.com/demo133/campusnet.git && cd campusnet
```

要求 Python 3.8+，**无第三方依赖**。

## 步骤 2：探测认证系统与门户（必做）

```sh
python <skill>/scripts/run.py detect --verbose
```

输出会给出：认证系统类型、门户地址、识别到的参数。把这个输出当作后续配置的依据。

- 探测失败或识别不出 → 读 `references/fingerprinting.md`
- 用户已经在某台机器上跑通过、只想改一处 → 用 `--portal` 直接指定，跳过自动探测

## 步骤 3：生成配置

优先走交互式向导（它会把这些都问一遍）：

```sh
python <skill>/scripts/run.py setup
```

向导里**「校园 Wi-Fi 名称」这一项一定要填** —— 它是"换过 Wi-Fi 后开机连不回校园网"的修复前提。

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

**密码存哪里 —— 这里有个坑，务必跟用户说清楚。**

`setup` 拿到密码后按顺序决定存哪：

1. **装了 `keyring`**（系统钥匙串）→ 问用户要不要存进去，**推荐存**。
   Windows 走凭据管理器，不落明文，这是最好的选择。
2. **加了 `--save-password`** → **明文**写进配置文件。
   Windows 上 `chmod` 不生效，就是明文躺在 `%APPDATA%\campusnet\config.json` 里。
3. **两个都没有** → **密码直接丢掉**。向导只打一句"密码未保存 —— 请用环境变量提供"，
   然后照常"配置已保存 ✔"结束。

第 3 种最坑：**向导跑完、看着一切正常，实际开机照样登录不了。**
用户说"setup 跑完了"但登录还是失败时，先查这个 ——
`campusnet doctor` 里账号那行会写"取不到密码"。

所以引导用户时，二选一，别让他走到第 3 条：

```sh
python -m pip install keyring          # 装完 setup 会问"存进钥匙串吗"，回车即可
python <skill>/scripts/run.py setup
```

无人值守（cron / 计划任务）**优先用环境变量 `CAMPUSNET_PASSWORD`**；
`--save-password` 只在"确实取不到环境变量"时才用。

### 登录前要先选运营商

```sh
python <skill>/scripts/run.py carrier          # 看当前设置
python <skill>/scripts/run.py carrier 移动      # 持久设置
python <skill>/scripts/run.py once --carrier 电信   # 只这一次
```

**必须讲清楚一个区别**：「校园电信 / 校园联通」和「电信 / 联通」在 Dr.COM 上是
**不同的服务类型**（走不同的 `R1`/`R3` 参数），不是"加不加账号后缀"的区别。
用户说不清时，让他看登录页的服务类型下拉框有哪几个选项。
认不出的运营商不会报错，会被当作账号后缀透传（如 `学号@神秘宽带`），
这恰好是很多学校的真实做法。

## 步骤 4：登录并验证

```sh
python <skill>/scripts/run.py once --verbose
```

`once` 默认是**安静模式**：已联网时一个字都不输出、退出码 0。
这是刻意设计 —— 它要被 cron 每 5 分钟调用一次，不能把日志刷满。
所以**排障时一定要加 `--verbose`**，否则看不到任何东西。

期望看到 `result:1`（成功）或 `result:2`/`3`（已在线，也算成功）。

## 步骤 5：装成自动

### 桌面端（Windows / macOS / Linux）

```sh
python <skill>/scripts/run.py autostart install
python <skill>/scripts/run.py autostart status    # 确认装好了
```

顺序很重要：**必须先 `wifi` 能连上校园网，再谈自动认证**。
桌面端"换过 Wi-Fi 后开机连不回校园网"的根因就是这个顺序 ——
程序原先只问"有没有网"，手机热点也有网，于是判定"无需认证"，
Wi-Fi 从头到尾没被碰过。现在 `wifi set` 会记住校园网并关闭其它网络的自动连接：

```sh
python <skill>/scripts/run.py wifi status
python <skill>/scripts/run.py wifi set <校园Wi-Fi名>
```

### 路由器（OpenWrt）

**路由器上不要用 `watch` 常驻守护**（白占内存），正确做法是 5 分钟一次 cron：

```sh
python3 -m campusnet autostart install --interval 5 --config /etc/campusnet/config.json
```

它会做三件事，**缺一不可**：写 `/etc/init.d/campusnet`（procd）、
写 `/etc/crontabs/root` 条目、启用并重启 cron 服务。
只做了第一件就以为装好了，是极常见的误判。

配置**必须放在 `/etc/campusnet/`，绝不能放 `/tmp`** —— `/tmp` 是 tmpfs，重启即清空。

路由器上装不了 Python（flash 太小）时，用仓库里的零依赖纯 shell 版：

```sh
scp community/openwrt/campusnet-openwrt.sh root@192.168.1.1:/usr/bin/
chmod +x /usr/bin/campusnet-openwrt.sh
```

它只支持 Dr.COM 的 JSONP 接口，不支持指纹识别和 Wi-Fi 管理，但占用几乎为零。

## 步骤 6：排障（"本来好好的，突然失效了"）

**第一步永远是先跑体检，不要凭猜测改配置：**

```sh
python <skill>/scripts/run.py doctor
```

它逐项检查并给出可以直接粘的修复命令。有 `✘` 就照着改。

体检没定位到时，读 `references/troubleshooting.md` —— 按**症状**查（不是按原因），
覆盖七类最常见故障：门户地址变了、运营商变了、配置在 `/tmp`、cron 服务被关、
cron 环境取不到密码、WAN 口 MAC/IP 变了、固件升级没保留配置。

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
- 需要 HTTPS 门户时，路由器上要额外装 `python3-openssl` + `ca-bundle`；
  内网门户绝大多数是 HTTP，一般用不上。

## 把结果反馈回来（重要）

这个项目最需要的是**不同学校的真实指纹**，而不是更多功能。
用户跑通或卡住时，引导他生成一份脱敏报告：

```sh
python <skill>/scripts/fingerprint.py
```

脚本会自动打码账号、IP、MAC、密码，只保留认证系统特征。
把生成的内容贴到 issue（模板见 `.github/ISSUE_TEMPLATE/fingerprint.md`）即可 ——
给一所新学校加支持通常就是加一条指纹规则的事。
