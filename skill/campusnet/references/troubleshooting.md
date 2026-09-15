# 排障：按症状查

**先跑体检，再查这里。**

```sh
python3 -m campusnet doctor
```

`doctor` 会逐项检查并在结论里给出可直接粘贴的修复命令。
只有它没定位到时，才按下面的症状往下查。

---

## 症状索引

| 用户描述的症状 | 看哪节 |
| --- | --- |
| 路由器上以前能自动登录，最近失效了 | A1 → A7（按顺序） |
| 手动跑通，定时任务里永远失败 | A5 |
| 提示账号密码正确，但就是说不出为什么失败 | A2 |
| 命令输出一片空白，什么都看不到 | B1 |
| 重启/断电/固件升级后就失效 | A3、A7 |
| 换了 Wi-Fi 之后开机连不回校园网 | B2 |
| 开机后要等很久才连上网，偶尔一直连不上 | B6 |
| 一直认证失败，学校要选运营商 | A2 |
| 报 SSL / ssl 相关错误 | B3 |
| `No module named campusnet` | B4 |
| 提示已联网，但其实上不了网 | B5 |
| 日志里某家接口全 404，最后却认证成功了 | B7 |

---

## A. 路由器（OpenWrt）上的七类故障

按**出现频率从高到低**排列。前三类覆盖绝大多数情况。

### A1. 门户地址或接口变了（最常见）

学校改版登录页、换认证服务器 IP、给接口加密，都会让写死的老地址失效。

```sh
python3 -m campusnet detect --verbose
```

探测到的地址与配置里的 `portal_ip` 不一致 → 改配置。

⚠️ **特别注意**：登录页 JS 里出现 `page_data_encrypt=1`，
说明学校启用了**加密认证接口**（`/eportal/portal/*`），
老的明文 `DDDDD` / `upass` 接口可能已被关闭。
这种情况用 `custom` provider 模板自己拼接口，见 `fingerprinting.md`。

### A2. 运营商 / 账号后缀变了

换了宽带套餐、学校调整了服务类型都会导致。
症状很典型：**账号密码都对，但返回的失败信息里看不出原因。**

```sh
python3 -m campusnet carrier          # 看当前设置
python3 -m campusnet carrier 移动      # 重设
```

「校园电信」和「电信」在 Dr.COM 上是**两个不同的服务类型**（`R1`/`R3` 不同），
不是后缀的区别。分不清时看登录页的服务类型下拉框有几个选项。

### A3. 配置或脚本在 `/tmp`

`/tmp` 是 tmpfs —— 重启、拔电、`sysupgrade` 都会清空。

```sh
python3 -m campusnet doctor | grep 配置位置
```

显示 `/tmp/...` 就是病根：

```sh
mkdir -p /etc/campusnet
mv /tmp/campusnet/config.json /etc/campusnet/
```

同样是 `/tmp` 的坑：如果 cron 条目指向的**脚本本身**在 `/tmp`，
重启后条目还在、脚本没了 —— 表现是"任务在跑但一直失败"。

### A4. cron 服务被关掉了

OpenWrt 的 cron 是可开关服务，部分固件默认关闭。

```sh
/etc/init.d/cron enabled && echo 已启用 || echo 没启用
logread | grep -i cron | tail -20

/etc/init.d/cron enable && /etc/init.d/cron start
```

### A5. 密码取不到（cron 环境问题，最阴的一个）

**手动跑通、cron 里永远失败 —— 十有八九是这个。**
cron 执行时的环境极简（只有 `PATH=/usr/sbin:/usr/bin:/sbin:/bin`），
**没有**你登录 shell 里 `export` 的 `CAMPUSNET_PASSWORD`。

修法：让命令自己去读文件。cron 条目改成：

```text
*/5 * * * * . /etc/campusnet/env && python3 -m campusnet once -q --config /etc/campusnet/config.json >>/var/log/campusnet.log 2>&1
```

其中 `/etc/campusnet/env` 内容为 `CAMPUSNET_PASSWORD=密码`，权限 `chmod 600`。

或者用 `--save-password` 把密码明文写进配置（同样 `chmod 600`）。
路由器通常是单人设备，这个取舍一般可以接受。

### A6. WAN 口 MAC 或 IP 变了

有些门户把认证会话绑定到 MAC 或 IP。重启后 MAC 变化
（部分固件会随机化）或 DHCP 分到新 IP，老会话就失效。

```sh
ifstatus wan | grep -E 'ipv4|mac'
```

正常情况下不用管 —— 每 5 分钟的 `once` 会自动重新认证。
如果**持续**失败，怀疑门户把 MAC 拉黑了。

### A7. 固件升级 / 恢复出厂

`sysupgrade` 会保留 `/etc/config/` 和部分 `/etc/`，
但 `/etc/init.d/` 里自己加的东西和 `/etc/crontabs/root` **不保证保留**
（取决于升级时是否勾选"保留配置"）。

升级后重跑一次即可（**幂等**，重复跑没问题）：

```sh
python3 -m campusnet autostart install --interval 5 --config /etc/campusnet/config.json
```

---

## B. 桌面端与通用问题

### B1. 命令什么都不输出

`once` / `login` 的**安静模式是刻意设计**的：已联网时一个字都不打印、退出码 0。
这是为了让它能安全地被 cron 每 5 分钟调用而不刷满日志。

排障时必须加 `--verbose`：

```sh
python3 -m campusnet once --verbose
python3 -m campusnet -v detect
```

### B2. 换过 Wi-Fi 之后开机连不回校园网

**根因是判断顺序错了**：程序原先只问"有没有网"，而手机热点也有网，
于是判定"已联网，无需认证"，校园 Wi-Fi 从头到尾没被碰过。

现在是 `先连 Wi-Fi（`ensure_wifi`）→ 再判是否需要认证`。修复用户侧配置：

```sh
python3 -m campusnet wifi status
python3 -m campusnet wifi set <校园Wi-Fi名>     # 记住校园网并关闭其它网络自动连接
```

注意 `netsh wlan connect` 是**异步**的，程序会轮询到真的关联上才走认证。

### B3. SSL / ssl 相关错误

- 桌面端：确保 Python 带 `ssl` 模块（绝大多数官方发行版都带）
- OpenWrt：`opkg install python3-openssl ca-bundle`

内网门户绝大多数是 **HTTP**，一般用不上。

### B4. `No module named campusnet`

源码目录的**父目录**要在 `PYTHONPATH` 里。最省事的做法：

```sh
scp -r campusnet root@192.168.1.1:/usr/lib/
export PYTHONPATH=/usr/lib
```

或直接把包放进 site-packages：

```sh
scp -r campusnet root@192.168.1.1:/usr/lib/python3.11/site-packages/
```

本 skill 里带的辅助脚本会自动处理这件事，不用手拼 `PYTHONPATH`。

### B5. 提示已联网，但实际上不了网

学校可能把探测地址加了白名单，导致"未认证却判定已联网"。
联网判定用的是双重校验：先探测劫持（`generate_204`），
再用真实站点内容校验。若仍然误判，用 `--force` 强制重新认证一次：

```sh
python3 -m campusnet once --force --verbose
```

### B6. 开机后 Wi-Fi 迟迟连不上（或偶尔一直连不上）

**和 B2 是两回事，别混。** B2 是"判断依据选错"（连上了别的网就不管了）；
这条是**抢得太早**：守护进程在登录时启动，但那一刻无线驱动、
Windows 的 `WlanSvc`、校园网的 SSID 广播往往还要再过十几秒才准备好。
这期间 `netsh wlan connect` 不是"连不上"，而是**命令根本执行不了**。

先确认是不是这个：

```sh
python3 -m campusnet wifi          # 看网卡是否就绪、当前 SSID、保存了哪些网络
python3 -m campusnet doctor        # 自启那一项是否真的装了
```

处理办法（默认值已经是这样，装过自启的**不用重装**）：

```sh
python3 -m campusnet watch --warmup 180 --warmup-gap 15 --retry-gap 60
python3 -m campusnet watch --warmup 0            # 想关掉热身
python3 -m campusnet watch --option wifi_attempts=3 --option wifi_ready_timeout=40   # 调得更凶
```

排查要点：

- **确认守护进程真的在跑**（`autostart status`）。这条症状最常见的真实原因
  其实是"自启压根没装"——没装的话开机自然没人去连。
- 如果同一台机器上还留着**别的开机脚本**（旧版 PowerShell 脚本、
  启动文件夹里的 `.vbs`、旧计划任务），它们会和 `campusnet` 抢同一块无线网卡：
  两边都在 `netsh wlan connect`，互相把对方踢掉。
  先确认只有一个在管，再查别的。
- 手动 `login` **没有**重试（刻意设计：要快速给结论）。
  所以"手动跑一次失败、守护模式却成功"是正常的，不是 bug。

### B7. 指纹识别成 drcom，但 drcom 全报 404，最后是 eportal 成功

**这是正常现象，不用改配置。** 实测遇到过：门户页面对 `drcom` 的指纹匹配度
1.00（Server 头也是 `DrcomServer1.0`），但 `/drcom/login` 这个 JSONP 接口
被关掉了 —— 80 / 801 / 803 三个端口全返 404。
随后 `eportal` 走 `:801/eportal/?c=ACSetting&a=Login` 成功。

也就是说：**页面长得像哪家 ≠ 哪家的接口开着**。
程序会按置信度依次尝试，`drcom` 失败后自动落到 `eportal`，不需要人工干预。

`--verbose` 里长这样：

```text
! [drcom] 失败：所有 Dr.COM 接口均未成功。最后一次返回：jsonp+wlanuserip：HTTP 404 未识别响应
• 使用 通用 eportal / 华为 AC 登录…
✔ [eportal] 成功：认证成功
```

想省掉那几轮 404，可以把 provider 固定下来：

```sh
python3 -m campusnet once --provider eportal
```

或者在配置里写 `"provider": "eportal"`。

**别把这里的结果当 bug 报。** 判断依据是最后有没有 `认证成功`，
中间某家的 404 只说明那家的接口没开。


---

## C. 不用代码手工复现一次认证

排障时最省时间的做法：绕开所有代码，直接打一次认证接口。

```sh
uclient-fetch -q -O - "http://10.99.0.1/drcom/login?callback=dr1003&DDDDD=学号&upass=密码&0MKKey=123456&R1=0&R2=&R3=0&R6=0&para=00&v6ip=&v=$(date +%s)"
```

`doctor` 会把这条命令按你的实际配置拼好，照抄即可。

期望返回 `dr1003({"result":1,...})`：

| `result` | 含义 |
| --- | --- |
| `1` | 成功 |
| `2` / `3` | 已经在线（也算成功） |
| 其它 | `msga` 字段里有失败原因 |

**这个测试能一刀切开两类问题：**

- 请求通了但认证失败 → 网络和门户都好，问题在参数或账号 → 查 A2
- 请求本身不通 → 网络层问题，**不是 campusnet 的问题** → 别再改配置

## D. 日志与速查命令（OpenWrt）

```sh
logread -e campusnet                       # campusnet 相关日志
logread -e crond                           # cron 有没有在跑任务
tail -50 /var/log/campusnet.log            # once 的输出（重启会清空）
cat /etc/crontabs/root                     # 定时任务长什么样
/etc/init.d/campusnet enabled && echo ok   # 自启是否启用
ps w | grep -E 'crond|campusnet'           # 进程在不在
ifstatus wan | grep ipv4                   # WAN 拿到 IP 了吗
ping -c 2 10.99.0.1                    # 门户通不通
```

> OpenWrt 上**没有** `crontab -l` / `crontab -`。busybox cron 读的是
> `/etc/crontabs/<用户名>` 这个文件，直接看它。
