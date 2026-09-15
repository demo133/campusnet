# 各平台的路径、自启位置与坑

同一套命令（`setup` / `login` / `once` / `autostart` / `doctor`）到处都能跑，
但**装在哪里、自启写在哪里、日志怎么看**每个平台都不一样。排障时先看这张表。

---

## 平台总览

| | Windows | macOS | Linux（桌面/服务器） | OpenWrt 路由器 |
| --- | --- | --- | --- | --- |
| 配置文件 | `%APPDATA%\campusnet\config.json` | `~/.config/campusnet/config.json` | `~/.config/campusnet/config.json` | `/etc/campusnet/config.json` |
| 自启方式 | 注册表 `Run` 项 | LaunchAgent | systemd 用户服务（无则 `crontab @reboot`） | procd init + cron |
| 自启位置 | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` | `~/Library/LaunchAgents/com.campusnet.watch.plist` | `~/.config/systemd/user/campusnet.service` | `/etc/init.d/campusnet` + `/etc/crontabs/root` |
| 定时粒度 | 登录时启动常驻 | 登录时启动常驻 | 登录时启动常驻 | **每 5 分钟一次** |
| 日志 | 前台输出 | `log show` / 前台输出 | `journalctl --user -u campusnet` | `logread -e campusnet` |
| 是否需要管理员 | 否（用户级） | 否 | 否（`--user`） | 需要 root |

> Windows 和 macOS/Linux 走的是**常驻守护（`watch`）**，
> OpenWrt 走的是**一次性任务 + cron**。这不是偷懒 ——
> 路由器内存紧张，常驻一个 Python 进程是纯浪费，详见 `../../docs/openwrt.md`。

---

## 环境变量（跨平台通用）

配置文件里的字段都能用环境变量覆盖，优先级更高：

| 变量 | 含义 |
| --- | --- |
| `CAMPUSNET_USERNAME` | 账号 |
| `CAMPUSNET_PASSWORD` | 密码 |
| `CAMPUSNET_PROVIDER` | 认证系统（`drcom` / `srun` / …） |
| `CAMPUSNET_OPTIONS` | provider 参数的 JSON 串 |

**`CAMPUSNET_PASSWORD` 是推荐做法**：密码不落盘。
但要注意它的副作用 —— 定时任务的环境里没有你 shell 里 `export` 的变量，
详见 `troubleshooting.md` 的 A5。

---

## Windows

```powershell
pip install git+https://github.com/demo133/campusnet.git
python -m campusnet setup
python -m campusnet autostart install
python -m campusnet autostart status      # 永远返回 0，可安全用于脚本
```

- 自启写在注册表 `HKCU\...\Run`，**不需要管理员**。
- Wi-Fi 管理走 `netsh`。`netsh wlan connect` 是**异步**的，
  程序会轮询到真的关联上才继续，不要手动加 `sleep` 等它。
- 看当前连的是哪个 Wi-Fi 时，注意 `netsh wlan show profile` 的输出里
  会有 `SSID 名称 :“xxx”` —— 那是**已保存的配置文件**，不是当前连接。
  程序的正则已经排除了它。如果你的脚本遇到"明明连着热点却显示校园网"，就是踩了这个。

## macOS

```sh
pip install git+https://github.com/demo133/campusnet.git
python3 -m campusnet setup
python3 -m campusnet autostart install
```

- 自启是 LaunchAgent（`~/Library/LaunchAgents/com.campusnet.watch.plist`），用户级，无需 sudo。
- Wi-Fi 管理走 `networksetup`。
- ⚠️ **macOS 自带 BSD 工具链**，和 Linux 的 GNU 版本行为不同。
  项目里踩过这个坑：纯 shell 版曾用 `awk` 的 `sprintf("%c", n)` 反查字符来构造 `ord()`，
  在 Linux 上正常，在 **BSD awk** 上返回的不是单字节，导致任何输入都被编成一串 `%3F`。
  现在改成"先把字节读成整数、再按整数运算"，三平台一致。
  **改动 shell 脚本时不要在 macOS 上只跑一遍就下结论。**

## Linux（桌面 / 服务器）

```sh
pip install git+https://github.com/demo133/campusnet.git
python3 -m campusnet setup
python3 -m campusnet autostart install
```

- 优先用 systemd **用户**服务（`~/.config/systemd/user/`），无需 sudo；
  没有 systemd 时退回 `crontab @reboot`。
- `autostart status` 对"没装 cron 包"和"systemd 不可用"都做了容错，
  **不会崩、也不会返回非零退出码** —— 因为它属于"报告状态"类命令。
- Wi-Fi 管理走 `nmcli`（NetworkManager）。服务器上通常没有无线网卡，
  这时 `wifi` 相关命令会明确说明"不支持"，**不会假装成功**。

## OpenWrt 路由器

```sh
opkg update
opkg install python3-light        # 约 2~3 MB；HTTPS 门户才需要 python3-openssl + ca-bundle
opkg install cron                 # 部分精简固件裁掉了 cron

scp -r campusnet root@192.168.1.1:/usr/lib/
mkdir -p /etc/campusnet           # 配置放这里，绝不要放 /tmp
chmod 600 /etc/campusnet/config.json

python3 -m campusnet autostart install --interval 5 --config /etc/campusnet/config.json
python3 -m campusnet autostart status
```

**必须记住的四件事：**

1. **没有 systemd。** OpenWrt 用 `/etc/rc.common` + procd 的 sysvinit 风格写法。
   往这里套 systemd 是白费功夫。
2. **没有 `crontab -l` / `crontab -`。** busybox cron 直接读 `/etc/crontabs/root`，
   看/改就编辑这个文件。
3. **配置和脚本不能放 `/tmp`。** tmpfs，重启即清空。
4. **`wifi` 系列命令不适用。** 路由器是上行设备，不是要切网的客户端。
   要改无线设置用 `uci`：

   ```sh
   uci show wireless
   uci set wireless.@wifi-iface[0].ssid='校园Wi-Fi名'
   uci commit wireless && wifi reload
   ```

**装不下 Python 时**（flash 只有 8 MB 的老机器），用零依赖的纯 shell 版：

```sh
scp community/openwrt/campusnet-openwrt.sh root@192.168.1.1:/usr/bin/
chmod +x /usr/bin/campusnet-openwrt.sh
/usr/bin/campusnet-openwrt.sh          # 手动跑一次
```

它的配置是标准 UCI 格式，写在 `/etc/config/campusnet`；
cron 条目为 `*/5 * * * * /usr/bin/campusnet-openwrt.sh`。
能力弱一些（只支持 Dr.COM 的 JSONP 接口，没有指纹识别和 Wi-Fi 管理），
但占用几乎为零。

---

## 命令支持矩阵

| 命令 | Windows | macOS | Linux | OpenWrt |
| --- | --- | --- | --- | --- |
| `setup` / `detect` / `login` / `status` | ✅ | ✅ | ✅ | ✅ |
| `once` | ✅ | ✅ | ✅ | ✅ **（路由器上该用的就是它）** |
| `doctor` | ✅ | ✅ | ✅ | ✅（额外查 crond 与易失目录） |
| `carrier` | ✅ | ✅ | ✅ | ✅ |
| `autostart` | ✅ 注册表 | ✅ LaunchAgent | ✅ systemd / crontab | ✅ procd + cron |
| `wifi` | ✅ `netsh` | ✅ `networksetup` | ✅ `nmcli` | ❌ 不适用，给 `uci` 提示 |
| `watch` | ✅ | ✅ | ✅ | ⚠️ 能跑但没必要，白占内存 |

## `wifi` 的三平台底层命令

| 动作 | Windows | macOS | Linux |
| --- | --- | --- | --- |
| 看当前 SSID | `netsh wlan show interfaces` | `networksetup -getairportnetwork` | `nmcli -t -f active,ssid dev wifi` |
| 扫描 | `netsh wlan show networks` | `airport -s` | `nmcli dev wifi list` |
| 连接 | `netsh wlan connect` | `networksetup -setairportnetwork` | `nmcli dev wifi connect` |
| 自动连接开关 | profile XML 的 `connectionMode` | `networksetup -setairportpower` / 网络顺序 | `nmcli con mod ... connection.autoconnect` |

任何一项在目标机器上不可用时，`connect()` 返回
`ok=False, supported=False`，**绝不假装成功**。
看到这个返回就说明该平台这条路没走通，不要继续假设 Wi-Fi 已经切好了。
