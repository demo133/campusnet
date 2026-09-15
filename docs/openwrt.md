# 在 OpenWrt 路由器上跑 campusnet

宿舍里最常见的用法是：**路由器当上行设备**，WAN 口（或无线中继）连校园网，
宿舍里的电脑手机全部藏在 NAT 后面。这样只要路由器认证一次，整间宿舍都有网。

这个文档解决三件事：

1. 怎么在路由器上把 campusnet 装起来并**每 5 分钟自动跑一次**；
2. **「本来跑得好好的，最近突然失效了」怎么排查**（这是最多人卡住的地方）；
3. 不想装 Python 怎么办 —— 有一个纯 shell 的替代品。

---

## 一、先想清楚：路由器上该用哪种方式

| 方式 | 适合谁 | 常驻内存 | 说明 |
| --- | --- | --- | --- |
| **cron + `campusnet once`** | 大多数人 | 0（跑完就退） | **推荐**，也是 `autostart` 在 OpenWrt 上默认走的路 |
| **procd 常驻守护** | 想秒级恢复 | ~20 MB | 路由器内存通常不宽裕，一般没必要 |
| **纯 shell 脚本** | 装不上 Python 的机器 | 0 | 见 [`community/openwrt/`](../community/openwrt/) |

为什么推荐 **cron 而不是常驻守护**：

- 路由器的 flash 和内存都很紧，Python 进程常驻是纯浪费；
- 5 分钟一次的粒度对一个"断线重连"的需求完全够用；
- 每次跑完就退，进程泄漏、句柄泄漏这类问题根本不会出现。

`campusnet once` 就是为此设计的：**已联网时一个字都不输出、退出码 0**，
只在线路真的掉了的时候才打日志、才非零退出。这样 `logread` 不会被刷满，
而"每 5 分钟一条错误"本身就变成了告警信号。

---

## 二、装 Python 版本

### 1. 装上 Python 和 cron

```sh
opkg update
opkg install python3-light
# 如果固件里没带 cron（部分精简固件会裁掉）
opkg install cron
```

> `python3-light` 就够了。campusnet **只用标准库**，不碰 `ctypes`、`ssl`、
> `keyring` 这些在 light 包里被裁掉的模块。
> 唯一需要注意的是：如果你们学校的门户是 **HTTPS**，
> 那需要 `opkg install python3-openssl`（`python3-light` 里没带 ssl）。
> 内网门户绝大多数是 HTTP，一般用不上。

### 2. 把 campusnet 放到路由器上

路由器上不方便 `git clone` + `pip install`，直接拷源码目录最省事：

```sh
# 在电脑上（源码目录的上一级）
scp -r campusnet root@192.168.1.1:/usr/lib/campusnet

# 在路由器上
cd /usr/lib/campusnet
python3 -m campusnet --version
```

或者更干净的做法 —— 直接把包放进 Python 的 site-packages：

```sh
# 电脑上
scp -r campusnet root@192.168.1.1:/usr/lib/python3.11/site-packages/
# 路由器上
python3 -m campusnet --version
```

### 3. 生成配置（**关键：别放在 /tmp**）

```sh
mkdir -p /etc/campusnet
cat > /etc/campusnet/config.json <<'EOF'
{
  "username": "你的学号",
  "provider": "auto",
  "portal_ip": "10.99.0.1",
  "options": { "carrier": "campus" }
}
EOF
chmod 600 /etc/campusnet/config.json
```

密码**不要**写进配置文件。路由器上单独放一个只有 root 能读的文件，
由 init 脚本或 cron 的前置命令导出：

```sh
cat > /etc/campusnet/env <<'EOF'
CAMPUSNET_PASSWORD=你的密码
EOF
chmod 600 /etc/campusnet/env
```

> ⚠️ **这是第 5 条排查项要盯的东西**：cron 执行任务时的环境**极简**，
> 只有 `PATH=/usr/sbin:/usr/bin:/sbin:/bin`，**没有**你登录 shell 里的任何变量。
> 你 `export CAMPUSNET_PASSWORD=xxx` 之后手动跑是通的，cron 里却永远是"取不到密码" ——
> 就是这个原因。所以要让命令自己去读文件，见下面 cron 条目的写法。

### 4. 一行命令装好定时任务

```sh
python3 -m campusnet autostart install --interval 5 --config /etc/campusnet/config.json
```

它会同时做三件事（**三件缺一不可**，很多人只做了第一件就以为装好了）：

| 动作 | 位置 | 漏掉会怎样 |
| --- | --- | --- |
| 写 procd init 脚本 | `/etc/init.d/campusnet` | 没法用 `start/enable` 管理 |
| 写 cron 条目 | `/etc/crontabs/root` | **根本不会定时跑** |
| 启用并重启 cron 服务 | `/etc/init.d/cron enable && start` | 条目躺在文件里，但服务是关的 |

装完看一眼：

```sh
python3 -m campusnet autostart status
```

期望输出类似：

```text
init 脚本：/etc/init.d/campusnet（已启用）
cron：已安装（*/5 * * * *）
crond：已启用
（OpenWrt）
```

### 5. 手动验证一次

```sh
/etc/init.d/campusnet start
logread -e campusnet
```

想立刻看到认证过程（`once` 是安静模式，要看得加 `--verbose` 和去掉 `-q`）：

```sh
python3 -m campusnet once --verbose --config /etc/campusnet/config.json
```

---

## 三、装的到底是什么

`autostart install` 在 OpenWrt 上生成两样东西。

### `/etc/init.d/campusnet`（procd init 脚本）

```sh
#!/bin/sh /etc/rc.common
START=95
STOP=10
USE_PROCD=1

PROG=python3
ARGS="-m campusnet once -q --config /etc/campusnet/config.json"

start_service() {
	procd_open_instance
	procd_set_param command $PROG $ARGS
	procd_set_param respawn 0 0 0
	procd_set_param stdout 1
	procd_set_param stderr 1
	procd_close_instance
}
```

注意这**不是 systemd unit**，是 OpenWrt 自己的 sysvinit 风格（`/etc/rc.common` + procd）。
往这里套 systemd 的写法是白费功夫。

`respawn 0 0 0` 是有意的 —— 这是个一次性任务，跑完就退，
不加这个的话 procd 会以为它崩了、疯狂重启。

### `/etc/crontabs/root`（真正的定时器）

```text
*/5 * * * * python3 -m campusnet once -q --config /etc/campusnet/config.json >>/var/log/campusnet.log 2>&1
```

三个细节值得说明：

- **路径是 `/etc/crontabs/root`，不是 `crontab -e`。** OpenWrt 用的是 busybox
  cron，它读的是 `/etc/crontabs/<用户名>` 这个文件。你在别处学到的
  `crontab -l` / `crontab -` 在路由器上都不存在。
- **`once -q` 而不是 `login`。** 见前面说的：安静是刻意的设计，不是偷懒。
- **日志重定向到 `/var/log/campusnet.log`。** `/var/log` 在 OpenWrt 上是
  tmpfs，重启清空 —— 这是故意的，免得日志把 flash 写坏。

---

## 四、「本来好好的，最近突然失效了」——排查清单

这是 OpenWrt 用户反馈最多的一类问题。按**出现频率从高到低**排列，
前三条覆盖了绝大多数情况。

### 0. 先跑一次体检

```sh
python3 -m campusnet doctor
```

它会逐项检查下面这些点，并给出可以直接粘的修复命令。有 `✘` 就照着改。

### 1. 门户地址或接口变了（最常见）

学校改版登录页、换认证服务器 IP、给接口加加密 —— 都会让写死的老地址失效。

```sh
# 看看现在门户还在不在、是什么系统
python3 -m campusnet detect --verbose
```

如果探测到的地址和配置里的 `portal_ip` 不一样，改配置：

```sh
# 编辑 /etc/campusnet/config.json，把 portal_ip 改成新地址
```

**特别留意**：如果登录页的 JS 里出现了 `page_data_encrypt=1` 之类的字样，
说明学校启用了**加密认证接口**（`/eportal/portal/*`），
这时候老式的明文 `DDDDD`/`upass` 接口可能已经被关掉了。
这种情况先用 `custom` provider 模板自己拼接口，把抓到的请求发到 issue 里。

### 2. 运营商 / 账号后缀变了

换了宽带套餐、学校调整了服务类型，都会导致这个。症状很典型：
**账号密码都对，但返回的失败信息里看不出原因。**

```sh
python3 -m campusnet carrier          # 看现在设的是什么
python3 -m campusnet carrier 移动      # 重新设一个
```

小心「校园电信」和「电信」的区别，详见
[README 的运营商一节](../README.md#登录前要先选运营商)。

### 3. 脚本被放进了 `/tmp`，重启/升级后没了

`/tmp` 是 tmpfs。**重启、拔电、固件升级都会清空。**

```sh
# 看看你的配置到底在哪
python3 -m campusnet doctor | grep 配置位置
```

如果显示 `/tmp/...`，那就是病根。挪到 `/etc/campusnet/` 去：

```sh
mkdir -p /etc/campusnet
mv /tmp/campusnet/config.json /etc/campusnet/
```

同样地，如果当初是手动塞的 cron 条目、而脚本本身在 `/tmp`，
重启后 cron 条目还在、**但脚本没了** —— 表现就是"任务在跑但一直失败"。

### 4. cron 服务被关掉了

OpenWrt 的 cron 是个可开关的服务。有些固件的默认状态就是关的，
或者被别的配置工具动过。

```sh
/etc/init.d/cron enabled && echo "已启用" || echo "没启用"
logread | grep -i cron | tail -20
```

修：

```sh
/etc/init.d/cron enable
/etc/init.d/cron start
```

### 5. 密码取不到（cron 环境问题，很阴）

手动跑通、cron 里永远失败 —— 十有八九是这个。
cron 的环境里没有 `CAMPUSNET_PASSWORD`（那是你登录 shell 的变量）。

修法：让命令自己去读文件。把 cron 条目改成：

```text
*/5 * * * * . /etc/campusnet/env && python3 -m campusnet once -q --config /etc/campusnet/config.json >>/var/log/campusnet.log 2>&1
```

或者干脆把密码用 `--save-password` 明文写进配置文件
（`chmod 600` 保护，路由器本来就是单人设备，这个取舍通常可以接受）。

### 6. WAN 口 MAC / IP 变了

学校门户有时会把认证会话绑定到 MAC 或 IP 上。
重启后路由器 MAC 变了（有些固件会随机化）、或者 DHCP 分到了新 IP，
老会话就失效了。

```sh
ifstatus wan | grep -E 'ipv4|mac'       # 看 WAN 现在是什么 IP
```

正常情况不用管 —— 每 5 分钟的 `once` 会自动重新认证。
如果**持续**失败，就要考虑是不是门户那边把 MAC 拉黑了。

### 7. 固件升级 / 恢复出厂设置

OpenWrt 的 `sysupgrade` **保留** `/etc/config/` 和部分 `/etc/` 下的文件，
但 `/etc/init.d/` 里自己加的东西、`/etc/crontabs/root`
**不保证保留**（取决于是否勾了"保留配置"）。

升级后重新跑一遍安装命令即可：

```sh
python3 -m campusnet autostart install --interval 5 --config /etc/campusnet/config.json
```

---

## 五、不装 Python：纯 shell 版本

有些机器 flash 小到装不下 Python（或者你就是不想装）。
[`community/openwrt/`](../community/openwrt/) 下有一个纯 busybox `sh` 写的版本，
只用 `uclient-fetch`（OpenWrt 自带）发请求，零依赖。

```sh
scp community/openwrt/campusnet-openwrt.sh root@192.168.1.1:/usr/bin/
chmod +x /usr/bin/campusnet-openwrt.sh
```

配置写在 `/etc/config/campusnet` 里（标准 UCI 格式）：

```sh
cat > /etc/config/campusnet <<'EOF'
config campusnet 'main'
	option enabled '1'
	option username '2200000000'
	option password '你的密码'
	option portal '10.99.0.1'
	option r1 '0'
	option r3 '0'
	option para '00'
	option suffix ''
EOF
```

手动跑一次：

```sh
/usr/bin/campusnet-openwrt.sh
```

然后进 crontab：

```text
*/5 * * * * /usr/bin/campusnet-openwrt.sh
```

它的能力比 Python 版弱（只支持 Dr.COM 的 JSONP 接口，
不做指纹识别、不做 Wi-Fi 管理），但胜在**几乎没有占用**，
而且在只有 8 MB flash 的老路由器上也能跑。

---

## 六、不用 Python 手工复现一次认证

排障时最省时间的做法：绕开所有代码，直接用 `uclient-fetch` 打一次接口。

`campusnet doctor` 会把这条命令给你拼好，照抄即可。以真实校园网环境为例：

```sh
uclient-fetch -q -O - "http://10.99.0.1/drcom/login?callback=dr1003\
&DDDDD=你的学号&upass=你的密码&0MKKey=123456\
&R1=0&R2=&R3=0&R6=0&para=00&v6ip=&v=$(date +%s)"
```

期望返回：

```json
dr1003({"result":1,"msg":1,"uid":"...","msga":""})
```

- `result:1` → 成功
- `result:2` 或 `3` → 已经在线上了（也算成功）
- 其它 → `msga` 字段里有失败原因

请求**通了但认证失败**，说明网络和门户都好，问题在参数或账号；
**请求本身不通**，说明是网络层问题（不是 campusnet 的问题）。

---

## 七、`campusnet` 在路由器上不管什么

如实说明，免得白折腾：

| 命令 | 路由器上的行为 |
| --- | --- |
| `wifi` / `wifi set` / `wifi connect` | **不适用**。路由器是上行设备，不是要切网的客户端。`campusnet wifi` 会给出对应的 `uci` 命令 |
| `autostart` | ✅ 走 OpenWrt 分支，写 `/etc/init.d/` + `/etc/crontabs/root` |
| `once` | ✅ 这是路由器上真正该用的命令 |
| `watch` | ⚠️ 能跑但没必要，白占内存 |
| `doctor` | ✅ 会检查 crond 状态和配置是否在易失目录 |
| `detect` / `login` / `status` | ✅ 正常 |

要改路由器的无线设置，用 OpenWrt 自己的 `uci`：

```sh
uci show wireless
uci set wireless.@wifi-iface[0].ssid='CampusWiFi'
uci commit wireless && wifi reload
```

---

## 八、日志与排障命令速查

```sh
logread -e campusnet                       # 只看 campusnet 相关的内核日志
logread -e crond                           # 看 cron 有没有在跑任务
tail -50 /var/log/campusnet.log            # once 的输出（重启会清空）
cat /etc/crontabs/root                     # 定时任务长什么样
/etc/init.d/campusnet enabled && echo ok   # 自启是否启用
ps w | grep -E 'crond|campusnet'           # 进程在不在
ifstatus wan | grep ipv4                   # WAN 拿到 IP 了吗
ping -c 2 10.99.0.1                    # 门户通不通
```

---

## 九、把经验反馈回来

如果你在 OpenWrt 上跑通了、或者卡住了，都欢迎开 issue。最有价值的三样东西：

1. `python3 -m campusnet detect --verbose` 的输出（**记得给账号、IP、MAC 打码**）；
2. `python3 -m campusnet doctor` 的输出；
3. 你的路由器型号 + OpenWrt 版本（`cat /etc/openwrt_release`）。

有了这些，给一所新学校加支持通常就是加一条指纹规则的事。
