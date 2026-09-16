# 更新日志

本文件记录所有值得注意的改动。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [0.1.1] - 2026-09-16

### 修复

- **图形版：设置窗口在小屏 / 高缩放本子上填不完表单**（用户反馈：
  「页面无法下滑、无法拉大」）——
  - 设置页改成**可滚动画布**，滚轮和右侧滚动条都能用，再小的屏也填得到
    「保存并立即连接」；
  - 窗口改为**可缩放**（原来写死 560×560 不可调），并按屏幕高度自适应，
    高度装不下内容时自动到屏幕底，剩下的靠滚动；
  - 探测日志框不再挤在设置页上方（那块 9 行的日志框正是把表单顶出
    窗口的元凶），只在主面板显示。

- **开机自启不再闪黑窗**——`watch` 用 `pythonw` 跑、图形版是无窗口 exe，
  但派生的 `netsh` / `ipconfig` 每次调用都会闪一个控制台窗口，开机头几轮
  探测集中执行就成了「终端连续跳很多下」。所有子进程统一加
  `CREATE_NO_WINDOW`（POSIX 平台不受影响）。

### 新增

- **watch 单实例锁**——同一台机器同时只允许一个守护进程，重复启动的实例
  安静退出（Windows 命名互斥体 / POSIX flock，均随进程退出自动释放），
  避免多个守护抢同一块无线网卡。

## [Unreleased]

### 新增

- **开源技能市场专用版 skill**（[`skill/redskill/`](skill/redskill/)）——
  有一类平台要求上传的 skill 包满足更死板的格式约束，直接拿通用的 skill
  目录去传会被拒，所以做了一份专用版：
  - 文件白名单只有 `.md .py .js .json .txt`：`.png` `.svg` `.yaml`
    `.gitignore` `.LICENSE` 会被拒 → `LICENSE` 改名成 `LICENSE.txt`，
    脚本保留 `.py`，不带任何图片；
  - **zip 解压后根目录必须直接是 `SKILL.md`**（套一层同名文件夹平台就找不到）；
  - 主文件全文 ≤10000 **字符**；行尾要 LF（CRLF 会让平台解析 frontmatter 失败）；
    单文件 ≤10MB、总 ≤30MB。
  新增 `skill/build_redskill.py`：**先校验再打包**，把上面这些前置成本地断言
  （含"正文里不能让人执行包里不存在的脚本"），任一条不满足就失败，
  绝不产出一个会被平台拒的包。
  打包产物见 `skill/dist/campusnet-redskill.zip`。

- **Wi-Fi 自动切回校园网**（`campusnet wifi`）——
  修掉「手动切到别的 Wi-Fi 后重启，不会再连回校园网」的问题。
  新增 `wifi status|list|connect|autoconnect|set|restore` 子命令，
  以及 `wifi_ssid` 配置项和 `watch --wifi` 参数。
- **运营商（ISP）选择支持**（`campusnet carrier`）——
  登录前要先选「移动 / 电信 / 联通」的学校现在也能用了。
  新增 `carrier` 子命令、`--carrier` 参数和向导第 4 步；
  Dr.COM 走 `R1` / `R3` / `para` + 账号后缀，Srun 走 `domain` 参数。
  新增 `campusnet.carrier` 模块做跨厂商的运营商归一化。
- **OpenWrt 路由器支持** —— 路由器上不适合跑常驻守护（flash 与内存都紧），
  所以 `campusnet autostart` 在 OpenWrt 上走的是 **procd init 脚本 +
  `/etc/crontabs/root` 每 N 分钟一次的 cron**，而不是别的平台那种常驻进程。
  新增 `is_openwrt()` 判定（只认 `/etc/openwrt_release`，比看有没有 `opkg` 准）、
  `_install_openwrt` / `_uninstall_openwrt` / `_status_openwrt`。
  完整指引与排障清单见新增的 [docs/openwrt.md](docs/openwrt.md)。
  另外路由器扮演的是上行设备而不是客户端，所以 `wifi` 子命令在它上面
  **明确降级**（`connect` 返回 `supported=False` 而不是谎报成功），
  并把该用的 `uci` 命令直接打出来。
- **`campusnet once`** —— 跑一次就走的命令，给 cron / 路由器用。
  与 `login` 的关键差别是**安静**：已联网时一个字都不输出、退出码 0；
  真没连上才打日志并非零退出。5 分钟一次的任务如果每次都写日志，
  `logread` 很快就被刷满，真正的问题反而被淹掉。
- **`campusnet doctor`** —— 逐项体检，专治「本来好好的，最近突然失效了」。
  检查网络、门户地址、账号密码、运营商、自启、定时任务（含 crond 是否启用）、
  配置是否落在 `/tmp` 这类易失目录；最后给出一条**不依赖本工具**的原始认证命令
  （`uclient-fetch` / `curl`），用来一刀切开"是网络问题还是程序问题"。
- **`--option k=v` 逃生舱** —— README 里一直写着、但实际**没有实现**的参数。
  现在补齐并可重复使用，用来直接写死供应商特有字段（`--option r1=1`）。
  值的解析刻意保守：**除 `true`/`false` 外一律当字符串** ——
  Dr.COM 的 `para` 合法值是 `"00"` / `"30"`，一旦被解析成整数，
  `para=00` 就会变成 `para=0`，服务端不认且报错看不出原因。
- **纯 shell 版的 OpenWrt 脚本**（[`community/openwrt/`](community/openwrt/)）——
  给 flash 小到装不下 Python 的机器用，只用 busybox 的 `uclient-fetch`，
  配置走标准 UCI 格式。
- **对话式 skill 包**（[`skill/campusnet/`](skill/campusnet/)）——
  把「判断场景 → 选对命令 → 按症状定位」这套流程封装成可安装的 skill。
  重点不在安装步骤（那本来就只有一行 `pip install`），而在
  **"装完坏了怎么自己修"**：`references/troubleshooting.md` 按**症状**索引，
  `SKILL.md` 里所有路径都走 `scripts/run.py`（自动在"已装的包"和
  "本机源码目录"之间定位，省得每次猜 `python` 还是 `python3`）。
  另带 `scripts/fingerprint.py`：一键生成**自动脱敏**的指纹报告
  （IPv4 / MAC / 密码字段 / 长数字全部打码），把"求指纹"这件事的门槛降到一条命令。
  设计与分发方式见 [docs/skill.md](docs/skill.md)。

### 修复

- **专用版 skill 包把脚本内联了，其实是多此一举**。第一版照着一条流传很广的说法
  （"这类平台只支持 Markdown / TXT，Python 脚本传不了"）把 `scripts/*.py`
  改成了 Markdown 里的代码块。按实测报错，**平台的文件白名单其实是
  `.md .py .js .json .txt` —— `.py` 是允许的**。现改为脚本作为真实文件随包发布，
  `references/helper-scripts.md` 只保留脱敏规则和手工复现命令
  （既能让人核对脚本行为，也去掉了一份重复代码）。
  同时补齐了之前漏掉的两条硬门槛：**SKILL.md 全文 ≤10000 字符**、
  **CRLF 会导致 frontmatter 解析失败（`name` / `description` 变空）** ——
  两条都已做成 `build_redskill.py` 的断言，并做了负向验证。

- **「开机有时候 wifi 没自动连接上」——修的是时机，不是判断逻辑**。
  之前处理的失败模式是"连到了别的网、判断依据选错"；这一条是**抢得太早**：

  守护进程在**登录时**启动，而那一刻无线驱动、Windows 的 `WlanSvc`、
  校园网的 SSID 广播往往还要再过十几秒才准备好。这期间
  `netsh wlan connect` 不是"连不上"，而是**命令根本执行不了**；
  旧逻辑失败一次就要等满一个检查周期（默认 10 分钟），
  体感就是"开机一直没网"。

  三层改动：

  1. **先等网卡就绪再动手**。新增 `wifi.interface_ready()` / `wifi.wait_for_radio()`
     —— 只有当"列得出无线接口、且无线电没被关掉"时才去发连接命令。
     判定刻意只看「无线电状态」这一个字段：拿整段 netsh 输出找"关闭"
     会撞上 `状态 : 已断开连接` 之类的字段，反而永远连不上。
  2. **一次不成要能重试**。`wifi.ensure_wifi()` 新增
     `attempts` / `retry_delay` / `ready_timeout`，并且重试时要能识别出
     "上一次的连接命令其实生效了、只是关联慢"。
     **默认仍是单次尝试** —— 手动 `login` 保持"快速给结论"的手感，
     只有守护模式走"耐心"那条路。
  3. **`watch` 分成开机热身 + 常规守护两段**。开头 180 秒内每 15 秒
     把「等网卡 → 切网 → 登录」整条重试一遍，一连上立刻转入常规节奏；
     之后哪一轮没弄通，用 60 秒快速重试，而不是干等十分钟 ——
     合盖唤醒、中途被切到热点也能很快补回来。
     新增 `--warmup` / `--warmup-gap` / `--retry-gap`，
     **默认值即为新行为，已装自启的用户重启后直接生效，不用重装**。

  顺手修掉一个隐患：`watch` 原来把异常捕获放在**循环外**，
  单轮出错会直接让守护进程退出；现在改成每轮单独兜住 ——
  守护进程要活好几天，provider 抽风、系统命令失败都不该让它死。
  新增 16 条测试覆盖上述判定、重试与两阶段节奏。
- **`SKILL.md` 缺少权限与依赖说明**。这类平台的《Skill 上传规范》明确要求
  "准确说明所需权限及用途、代码逻辑透明"，这也是人工复审会看的地方。
  新增「依赖与权限说明」一节：需要什么、会读取什么、**不会做什么**、
  附带脚本各干什么、已知边界。
- **全局选项 `-v` / `-c` / `--timeout` 放在子命令之后会报错**。
  `-v` 原先只挂在主解析器上，于是 `campusnet detect --verbose` 直接报
  `unrecognized arguments: --verbose` —— 而 README、`docs/openwrt.md`
  以及给用户的排障说明里，**写的全都是这种写法**，照着文档打就报错。
  现在全局选项同时挂在每个子命令上（`parents=`），两种位置都成立。
  子解析器那份的 `default` 必须是 `argparse.SUPPRESS`，
  否则子解析器的默认值会把主解析器已取到的值覆盖掉 —— 已加测试钉住。
- **仓库里清掉了所有个人隐私信息**（学号 / 门户 IP / 校园 Wi-Fi 名 / 校名 /
  本机网络与硬件指纹）。项目早期图省事，拿作者自己的真实值当"示例值"
  写进了 README、`docs/`、`skill/` 和测试夹具，散落在 20 多个文件里。
  现在统一换成中性占位：
  学号 → `2200000000`，门户 → `10.99.0.1`，SSID → `CampusWiFi`，
  校名 → "某高校 / 真实校园网环境"；测试夹具里的网卡 MAC、AP BSSID、网卡 GUID
  和网卡型号也都换成了教科书式占位值。
  同时**新增 `tests/test_privacy.py` 作为回归护栏** —— 把这些真实值固化成断言，
  谁再写回来本地 pytest 就直接红，不用等推到 GitHub 才发现；
  它连打包好的 zip 一起查，因为那是最容易被外人拿到的一份。
  顺带删掉了构建产物 `campusnet.egg-info/`：它虽然被 `.gitignore` 排除，
  但会跟着源码目录到处复制，里面存着一份旧的 README 快照。
- **去掉了所有内部制作痕迹**。`SKILL.md` 的 frontmatter 里原先带着
  一个内部标记键（会被原样带到用户机器上），已删除；
  `docs/skill.md` 里写死的产品专属技能目录路径改成中性的「技能目录」，
  不再把用户绑在某个特定产品上；发布说明里对某个工具名的致谢也删了。
  这条同样有断言守着（`test_no_internal_marker` +
  `test_skill_frontmatter_has_no_internal_keys`）。

- **换过 Wi-Fi 之后开机连不回校园网**。
  原因是判断顺序错了：原先只问「有没有网」，而连着手机热点一样有网，
  于是直接判定「已联网，无需认证」，Wi-Fi 从头到尾没被碰过。
  现在改为**先确认连的是不是校园网，再判断有没有网**——
  顺序反了这就是 bug，所以专门加了回归测试钉住它。
  分两步修：`wifi set <名称>` 让登录前自动切回（应急）；
  `wifi autoconnect` 关掉其它网络的自动连接（治本，让开机时没得抢）。
- **运营商代号不幂等**：`normalize("campus_telecom")` 会因子串匹配
  降级成 `telecom`，把 Dr.COM 的「校园电信」（`R1=1`）悄悄变成纯「电信」
  （`R1=0`），认证必然失败且看不出原因。现在加了两道保护：
  标准代号直接返回、纯 ASCII 别名要求词边界。
- **「校园宽带(移动)」被认成「校园用户」**：子串匹配命中了更短的
  「校园」而不是用户真正想说的「移动」。现在按别名长度从长到短匹配。
- **`wifi` 报告类命令在无网卡的机器上返回非零**，导致 CI 全红。
  `wifi` / `wifi status` / `wifi list` / `wifi autoconnect` 现在恒返回 0；
  `wifi connect` 真失败时仍返回非零。
- **纯 shell 版在 macOS 上完全不可用**（`urlencode` 恒返回一串 `%3F`）。
  原因是它用 `awk` 的 `sprintf("%c", n)` 反查字符来实现 `ord()`，
  而 macOS 自带的是 **BSD awk**，它对 0..255 里一部分值不返回单字节。
  Linux 的 `mawk` / busybox awk 没这个毛病，所以表现为
  **「Linux 全绿、macOS 全红」**。现在改成先把字节读成十进制整数
  （`od -An -v -tu1`）再按整数运算，三平台结果一致。
  顺带修掉一个一直存在但没被测出来的问题：**中文密码以前是编错的**
  （`length()` / `substr()` 走字节，不认 UTF-8）。
- **两条「只在 Linux 上挂」的测试断言**。
  一条断言安装提示文案里不含 `/tmp/`，但 Linux 的 `tmp_path` 本身就在
  `/tmp/pytest-of-<user>/` 下，于是把 pytest 自己的临时目录当成了证据（假阳性）；
  另一条在 `crontab` 不存在时把 `autostart status` 搞崩、返回了非零退出码。
  前者改成对**文件内容**断言，后者给 `_status_linux` 加了
  `check=False` + 吞 `OSError` 的保护 ——
  「报告状态」类命令必须永远返回 0。

### 计划中

- 收集更多学校的门户指纹，把 `srun` / `ruijie` / `eportal` 从"已实现"推进到"已实测"
- Docker 镜像（给树莓派用户）
- 登录失败时的自动重试退避策略
- OpenWrt `.ipk` 软件包：纯 Python 包交叉编译本身不难（写个 `Makefile`
  放进 package feed，用对应架构的 SDK 构建即可），难的是**依赖**——
  `python3-light` 本身就有 2~3 MB，把它列为运行时依赖等于抵消了
  "省空间"这个卖点；另外配置要不要改走 UCI、`sysupgrade` 之后保不保留，
  都是要单独取舍的事。目前的判断是"先用 scp 拷源码 + 纯 shell 版兜底"，
  等确实有人需要再做成包。

## [0.1.0] - 2026-09-13

首个公开版本。

### 新增

- **多厂商认证支持**：`drcom`（城市热点）、`srun`（深澜）、`ruijie`（锐捷）、
  `eportal`（华为 / 通用 ACSetting）、`custom`（自定义模板）
- **门户自动指纹识别**：探测门户页面并按置信度排序 provider，`auto` 模式自动选择
- **双重联网判定**：`generate_204` 劫持探测 + 真实网页内容校验，避免被白名单误判为已联网
- **CLI**：`setup` / `detect` / `login` / `watch` / `status` / `providers` / `autostart`
- **开机自启**：Windows 注册表 `Run` 项、macOS LaunchAgent、Linux systemd 用户服务
  （无 systemd 时退回 crontab `@reboot`）
- **守护模式**：常驻轮询，联网正常时完全不产生日志
- **凭据管理**：环境变量 / `keyring` / 配置文件 / 交互输入四级优先级，默认不落盘

### 修复

- **在默认编码非 UTF-8 的控制台上会崩溃**（英文版 Windows、CI runner）。
  输出里的中文和 `─` `✔` 这类字符编不出来时会抛 `UnicodeEncodeError`，
  导致 `campusnet providers` / `status` 等命令直接以退出码 1 结束。
  现在：需要时自动切到 UTF-8，切不了就降级成 ASCII 字符，绝不崩。
- CI 增加 `PYTHONIOENCODING=cp1252` 的冒烟步骤，在三个平台上锁定这个回归
- `campusnet status` 不再因为"未联网"返回非零退出码（报告状态不是错误）；
  需要脚本判断的用新增的 `status --check`

### 实测

- 在 **某高校** 真实门户上验证通过：自动识别出 `Server: DrcomServer1.0`，
  `drcom` 置信度 1.00，正确提取本机 IP 与门户地址

### 说明

- `srun` / `ruijie` / `eportal` 三个 provider 目前只有单元测试覆盖
  （请求参数拼装与响应解析），**尚未在真实服务器上验证**，欢迎反馈
- Python 3.8+，无第三方依赖

[Unreleased]: https://github.com/demo133/campusnet/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/demo133/campusnet/releases/tag/v0.1.0
