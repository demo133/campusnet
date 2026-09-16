"""开机自启：Windows / macOS / Linux / OpenWrt 四套实现。

统一跑 ``python -m campusnet watch``，Windows 上换成 ``pythonw.exe`` 以免弹黑框。

**OpenWrt 例外，而且是最需要注意的一个平台**（见 :func:`is_openwrt`）：

路由器上不适合跑常驻守护 —— flash 空间小、内存紧、Python 装上就有十几兆。
所以 OpenWrt 分支用的是 **procd init 脚本（跑一次就退）＋ 5 分钟一次 cron**，
而不是别的平台上那种"装一个守护进程一直挂着"的做法。
"""

from __future__ import annotations

import contextlib
import os
import platform
import shlex
import shutil
import subprocess
import sys

from .procflags import no_window_kwargs

APP_NAME = "campusnet"
LABEL = "com.campusnet.watch"

#: OpenWrt 上放自启脚本和 cron 的位置（不放在 /tmp —— 那里重启就没了）
OPENWRT_INIT_PATH = "/etc/init.d/{}".format(APP_NAME)
OPENWRT_CRON_PATH = "/etc/crontabs/root"
#: OpenWrt 上提醒用户把配置放哪（别放 /tmp）
OPENWRT_CONFIG_HINT = "/etc/campusnet/config.json"


# -------------------------------------------------------------------- 平台判定
def is_openwrt() -> bool:
    """这是不是一台 OpenWrt 路由器。

    只认 OpenWrt 自己那个 ``/etc/openwrt_release`` —— 比判断
    "有没有 ``opkg``" 或"是不是嵌入式"都准得多，
    装过 Entware 的普通路由器、树莓派上的 LEDE 分支都能正确区分出来。
    """
    if platform.system() != "Linux":
        return False
    return os.path.exists("/etc/openwrt_release")


def _has_procd() -> bool:
    """有没有 procd（现代 OpenWrt 的 init 系统）。

    procd 是 ``/sbin/procd``；老版本或者被裁过的固件里没有，
    这时退回纯 cron —— 功能一样，只是少了"开机立刻跑一次"。
    """
    return os.path.exists("/sbin/procd") or os.path.exists("/etc/init.d/cron")


def _which_any(*names: str) -> str:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return ""


def _python_for_router() -> str:
    """路由器上可用的 Python 解释器。

    优先 ``python3``；OpenWrt 的 ``python3-light`` 也能跑这个工具
    （只用标准库的 urllib / json / socket，不碰 ctypes / ssl 的高级特性）。
    """
    return _which_any("python3", "python") or "python3"


def _run_quiet(command: list, text: bool = False):
    """跑一条命令，忽略一切失败。

    自启相关的命令（``systemctl`` / ``launchctl`` / ``/etc/init.d/xxx``）经常因为
    权限、服务没装、容器里没有 init 而失败 —— 那些都不该让安装流程崩。
    真要失败，后面的 ``status()`` 会如实反映出来。

    ``check=False`` 是**故意的**：OpenWrt 上没有 ``systemctl``、
    受限容器里没有 ``launchctl``，非零退出是常态而不是异常，
    而调用方只关心 ``returncode``。外面还裹了一层 ``try``，
    是因为最极端的情况下（命令不存在且没被 ``shutil.which`` 拦住）
    ``subprocess`` 会直接抛 ``FileNotFoundError``。
    """
    try:
        return subprocess.run(command, capture_output=True, text=text,
                              errors="replace", check=False,
                              **no_window_kwargs())
    except Exception:  # 探测类操作不该影响安装结果
        return None


# -------------------------------------------------------------------- 命令构造
def _base_command(config_path: str, interval: int = 10) -> list:
    python = _python_executable()
    args = [python, "-m", "campusnet", "watch", "--interval", str(interval)]
    if config_path:
        args += ["--config", config_path]
    return args


def _once_command(config_path: str = "") -> list:
    """跑一次就退的命令 —— cron 用的就是这个。

    用 ``once`` 而不是 ``login``：前者在已联网时**一个字都不输出**，
    后者每次都会打几行。5 分钟一次的任务如果每次都写日志，
    ``logread`` 很快就被刷满，真正的问题反而被淹掉了。
    """
    args = [_python_for_router(), "-m", "campusnet", "once", "-q"]
    if config_path:
        args += ["--config", config_path]
    return args


def _python_executable() -> str:
    """Windows 上优先用 pythonw.exe（无控制台窗口）。"""
    exe = sys.executable or "python"
    if platform.system() == "Windows":
        candidate = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(candidate):
            return candidate
    return exe


def _quote(args: list) -> str:
    if platform.system() == "Windows":
        return subprocess.list2cmdline(args)
    return " ".join(shlex.quote(part) for part in args)


# -------------------------------------------------------------------- 对外接口
def install(config_path: str = "", interval: int = 10) -> str:
    system = platform.system()
    if system == "Windows":
        return _install_windows(config_path, interval)
    if system == "Darwin":
        return _install_macos(config_path, interval)
    # OpenWrt 必须排在通用 Linux 前面：它有 systemd 才怪，
    # 但 /etc/init.d/cron 是存在的，走 _install_linux 会误判。
    if is_openwrt():
        return _install_openwrt(config_path, interval)
    return _install_linux(config_path, interval)


def uninstall() -> str:
    system = platform.system()
    if system == "Windows":
        return _uninstall_windows()
    if system == "Darwin":
        return _uninstall_macos()
    if is_openwrt():
        return _uninstall_openwrt()
    return _uninstall_linux()


def status() -> str:
    system = platform.system()
    if system == "Windows":
        return _status_windows()
    if system == "Darwin":
        return _status_macos()
    if is_openwrt():
        return _status_openwrt()
    return _status_linux()


# -------------------------------------------------------------------- Windows
WINDOWS_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _install_windows(config_path: str, interval: int) -> str:
    import winreg  # type: ignore

    command = _quote(_base_command(config_path, interval))
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY, 0,
                        winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
    return "已写入注册表启动项 HKCU\\{} · {}\n  {}".format(WINDOWS_RUN_KEY, APP_NAME, command)


def _uninstall_windows() -> str:
    import winreg  # type: ignore

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
        return "已移除注册表启动项"
    except FileNotFoundError:
        return "没有找到启动项（可能本来就没装）"
    except OSError as exc:
        return "移除失败：{}".format(exc)


def _status_windows() -> str:
    import winreg  # type: ignore

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY, 0,
                            winreg.KEY_QUERY_VALUE) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
        return "已安装（注册表启动项）\n  {}".format(value)
    except FileNotFoundError:
        return "未安装"
    except OSError as exc:
        return "读取失败：{}".format(exc)


# -------------------------------------------------------------------- macOS
def _macos_plist_path() -> str:
    return os.path.expanduser("~/Library/LaunchAgents/{}.plist".format(LABEL))


def _install_macos(config_path: str, interval: int) -> str:
    path = _macos_plist_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    python = _python_executable()
    args = [python, "-m", "campusnet", "watch", "--interval", str(interval)]
    if config_path:
        args += ["--config", config_path]
    program_args = "\n".join(
        "        <string>{}</string>".format(a) for a in args
    )
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        "<plist version=\"1.0\">\n"
        "<dict>\n"
        "    <key>Label</key>\n"
        "    <string>{label}</string>\n"
        "    <key>ProgramArguments</key>\n"
        "    <array>\n{args}\n    </array>\n"
        "    <key>RunAtLoad</key>\n    <true/>\n"
        "    <key>KeepAlive</key>\n    <true/>\n"
        "    <key>StandardOutPath</key>\n    <string>/tmp/{label}.log</string>\n"
        "    <key>StandardErrorPath</key>\n    <string>/tmp/{label}.err</string>\n"
        "</dict>\n"
        "</plist>\n"
    ).format(label=LABEL, args=program_args)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(plist)

    if shutil.which("launchctl"):
        subprocess.run(["launchctl", "unload", path], capture_output=True)
        subprocess.run(["launchctl", "load", path], capture_output=True)
    return "已安装 LaunchAgent：{}".format(path)


def _uninstall_macos() -> str:
    path = _macos_plist_path()
    if not os.path.exists(path):
        return "没有找到 LaunchAgent（可能本来就没装）"
    if shutil.which("launchctl"):
        subprocess.run(["launchctl", "unload", path], capture_output=True)
    os.remove(path)
    return "已移除 LaunchAgent"


def _status_macos() -> str:
    path = _macos_plist_path()
    return "已安装: {}".format(path) if os.path.exists(path) else "未安装"


# -------------------------------------------------------------------- Linux
def _systemd_unit_path() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "systemd", "user", "{}.service".format(APP_NAME))


def _install_linux(config_path: str, interval: int) -> str:
    if shutil.which("systemctl"):
        path = _systemd_unit_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        unit = (
            "[Unit]\n"
            "Description=campusnet 校园网自动登录\n"
            "After=network-online.target\n"
            "Wants=network-online.target\n\n"
            "[Service]\n"
            "Type=simple\n"
            "ExecStart={exec}\n"
            "Restart=always\n"
            "RestartSec=30\n\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        ).format(exec=_quote(_base_command(config_path, interval)))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(unit)
        subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", APP_NAME], capture_output=True)
        return "已安装 systemd 用户服务：{}".format(path)

    # 没有 systemd 就退回 crontab @reboot
    line = "@reboot {} >/dev/null 2>&1".format(_quote(_base_command(config_path, interval)))
    existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True, errors="replace")
    current = existing.stdout if existing.returncode == 0 else ""
    if line not in current:
        new = (current.rstrip("\n") + "\n" + line + "\n").lstrip("\n")
        subprocess.run(["crontab", "-"], input=new, text=True)
    return "已写入 crontab @reboot"


def _uninstall_linux() -> str:
    if shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "disable", "--now", APP_NAME], capture_output=True)
        path = _systemd_unit_path()
        if os.path.exists(path):
            os.remove(path)
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
        return "已移除 systemd 用户服务"

    existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True, errors="replace")
    if existing.returncode != 0:
        return "没有找到 crontab 条目"
    kept = [line for line in existing.stdout.splitlines() if APP_NAME not in line]
    subprocess.run(["crontab", "-"], input="\n".join(kept) + "\n", text=True)
    return "已从 crontab 移除"


def _status_linux() -> str:
    """Linux 上的自启状态。

    **这是一条"报告状态"的命令，绝不允许抛异常。** 它跑在别人的机器上：
    ``crontab`` 可能因为没装 cron 包而不存在，``systemctl --user`` 在没有
    user session 的容器 / CI runner 里会直接失败。任何一种情况都不该让
    ``campusnet autostart status`` 以非零退出 —— 那会让人以为自启坏了，
    而实际上什么都没坏，只是没法判断。

    所以：所有外部命令都加 ``check=False`` 并吞掉 ``OSError``，
    最坏的情况是回答"未安装"，而不是崩掉。
    """
    if shutil.which("systemctl"):
        with contextlib.suppress(OSError):
            result = subprocess.run(["systemctl", "--user", "is-enabled", APP_NAME],
                                    capture_output=True, text=True, errors="replace",
                                    check=False)
            state = result.stdout.strip() or "not-found"
            if state == "enabled":
                return "已安装（systemd 用户服务，enabled）"
            return "未启用（systemd: {}）".format(state)
        return "未安装（systemd 不可用）"

    with contextlib.suppress(OSError):
        existing = subprocess.run(["crontab", "-l"], capture_output=True, text=True,
                                  errors="replace", check=False)
        if existing.returncode == 0 and APP_NAME in existing.stdout:
            return "已安装（crontab @reboot）"
    return "未安装"


# -------------------------------------------------------------------- OpenWrt
#: 默认的检查间隔（分钟）。路由器上不宜太短 —— 每次都要走一次 TCP 握手，
#: 门户本身也会有压力；5 分钟足够覆盖"断了以后能很快回来"。
OPENWRT_DEFAULT_INTERVAL = 5

#: procd init 脚本。注意这是 **OpenWrt 自己的 sysvinit 风格**，
#: 不是 systemd unit —— 别拿 systemd 的写法往这儿套。
_OPENWRT_INIT = """#!/bin/sh /etc/rc.common
# campusnet 校园网自动登录
#
# 这个脚本只是 cron 任务的一个"托管壳"：真正的认证动作由
# /etc/crontabs/root 里每 N 分钟一次的 once 命令完成。
# 用它是因为 cron 条目本身没有"启动/停止"的概念，
# 有了 init 脚本就能用 /etc/init.d/campusnet start|stop|enable 管。

START=95
STOP=10
USE_PROCD=1

PROG={python}
ARGS="-m campusnet once -q{config_arg}"

start_service() {{
	procd_open_instance
	procd_set_param command $PROG $ARGS
	# 一次性任务：跑完就退，不重启（respawn 会让它疯狂重跑）
	procd_set_param respawn 0 0 0
	procd_set_param stdout 1
	procd_set_param stderr 1
	procd_close_instance
}}

stop_service() {{
	:
}}

reload_service() {{
	stop
	start
}}
"""


def _openwrt_cron_line(config_path: str, interval: int) -> str:
    command = " ".join(shlex.quote(part) for part in _once_command(config_path))
    # cron 的环境极简：PATH 里只有 /usr/sbin:/usr/bin:/sbin:/bin，
    # 而且**没有**你登录 shell 里的环境变量。所以把 PATH 显式写死，
    # 顺便把日志按日期截断一下，免得 logread 被刷爆。
    return "{base} {command} >>{log} 2>&1".format(
        base="*/{} * * * *".format(max(1, int(interval))),
        command=command,
        log="/var/log/campusnet.log",
    )


def _write_text(path: str, body: str, mode: int = 0o644) -> None:
    """写文件并把父目录建出来。

    单独抽出来是因为 ``os.path.dirname("/etc/crontabs/root")`` 在正常情况
    返回 ``/etc/crontabs``，但如果路径是被改写过的（测试里会这么干），
    有可能返回空串 —— 那时 ``os.makedirs("")`` 会直接抛。
    """
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    with contextlib.suppress(OSError):
        # FAT32 的 U 盘、某些 overlay 上 chmod 会失败，但文件已经写下去了
        os.chmod(path, mode)


def _install_openwrt(config_path: str, interval: int = OPENWRT_DEFAULT_INTERVAL) -> str:
    """OpenWrt：写 procd init 脚本 + 写 cron 条目 + 启用 cron 服务。

    三件事缺一不可，很多人只做了第一件，所以「装完不生效」：

    1. ``/etc/init.d/campusnet`` —— 让任务可被 ``start/enable`` 管理；
    2. ``/etc/crontabs/root`` —— 真正定时触发的地方（**不是** ``crontab -e``）；
    3. ``/etc/init.d/cron enable && start`` —— crond 本身默认可能是关的。

    另外**故意不把任何东西写进 /tmp**：那是 tmpfs，重启/固件升级就没了，
    这正是很多人"本来跑得好好的，最近突然失效"的原因。
    """
    notes = []

    # 1) init 脚本
    config_arg = ""
    if config_path:
        config_arg = " --config {}".format(shlex.quote(config_path))
    init_body = _OPENWRT_INIT.format(python=_python_for_router(), config_arg=config_arg)
    try:
        _write_text(OPENWRT_INIT_PATH, init_body, mode=0o755)
        notes.append("已写入 {}".format(OPENWRT_INIT_PATH))
    except OSError as exc:
        return "写入 {} 失败：{}（需要 root 权限）".format(OPENWRT_INIT_PATH, exc)

    # 2) cron 条目（幂等：先删旧的再写新的）
    line = _openwrt_cron_line(config_path, interval)
    try:
        existing = ""
        if os.path.exists(OPENWRT_CRON_PATH):
            with open(OPENWRT_CRON_PATH, "r", encoding="utf-8", errors="replace") as fh:
                existing = fh.read()
        kept = [item for item in existing.splitlines() if APP_NAME not in item]
        kept.append(line)
        _write_text(OPENWRT_CRON_PATH, "\n".join(kept).strip("\n") + "\n", mode=0o600)
        notes.append("已写入 {}（每 {} 分钟一次）".format(OPENWRT_CRON_PATH, interval))
    except OSError as exc:
        return "写入 {} 失败：{}（需要 root 权限）".format(OPENWRT_CRON_PATH, exc)

    # 3) 把 cron 服务本身启用起来 —— 这一步最容易被漏掉
    if os.path.exists("/etc/init.d/cron"):
        for action in ("enable", "restart"):
            _run_quiet(["/etc/init.d/cron", action])
        notes.append("已启用并重启 /etc/init.d/cron")
    else:
        notes.append("注意：没找到 /etc/init.d/cron，请确认固件里带了 cron")

    notes.append("")
    notes.append("配置请放在 {} （不要放 /tmp，重启会丢）".format(OPENWRT_CONFIG_HINT))
    notes.append("立即验证一次：/etc/init.d/campusnet start && logread -e campusnet")
    return "\n  ".join(notes)


def _uninstall_openwrt() -> str:
    removed = []

    # 停掉并移除 init 脚本
    if os.path.exists(OPENWRT_INIT_PATH):
        _run_quiet([OPENWRT_INIT_PATH, "stop"])
        _run_quiet([OPENWRT_INIT_PATH, "disable"])
        try:
            os.remove(OPENWRT_INIT_PATH)
            removed.append("已移除 {}".format(OPENWRT_INIT_PATH))
        except OSError as exc:
            removed.append("移除 init 脚本失败：{}".format(exc))

    # 从 crontab 里剔掉我们自己的行
    try:
        if os.path.exists(OPENWRT_CRON_PATH):
            with open(OPENWRT_CRON_PATH, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
            kept = [item for item in lines if APP_NAME not in item]
            _write_text(OPENWRT_CRON_PATH,
                        "\n".join(kept).strip("\n") + ("\n" if kept else ""),
                        mode=0o600)
            removed.append("已从 {} 移除 cron 条目".format(OPENWRT_CRON_PATH))
        if os.path.exists("/etc/init.d/cron"):
            _run_quiet(["/etc/init.d/cron", "restart"])
        removed.append("已重启 crond 让改动生效")
    except OSError as exc:
        removed.append("清理 crontab 失败：{}".format(exc))

    return "\n  ".join(removed) if removed else "没有找到 campusnet 的定时任务"


def _openwrt_enabled(path: str) -> bool:
    """``/etc/init.d/<x> enabled`` 的退出码。"""
    result = _run_quiet([path, "enabled"])
    return bool(result is not None and result.returncode == 0)


def _status_openwrt() -> str:
    lines = []

    if os.path.exists(OPENWRT_INIT_PATH):
        lines.append("init 脚本：{}（{}）".format(
            OPENWRT_INIT_PATH, "已启用" if _openwrt_enabled(OPENWRT_INIT_PATH) else "未启用"))
    else:
        lines.append("init 脚本：未安装")

    cron_line = ""
    if os.path.exists(OPENWRT_CRON_PATH):
        try:
            with open(OPENWRT_CRON_PATH, "r", encoding="utf-8", errors="replace") as fh:
                for item in fh.read().splitlines():
                    if APP_NAME in item:
                        cron_line = item
                        break
        except OSError:
            pass
    if cron_line:
        # 只把 "*/5 * * * *" 这一段拿出来显示，整行太长
        schedule = " ".join(cron_line.split()[:5])
        lines.append("cron：已安装（{}）".format(schedule))
    else:
        lines.append("cron：未安装")

    if os.path.exists("/etc/init.d/cron"):
        cron_up = _openwrt_enabled("/etc/init.d/cron")
        lines.append("crond：{}".format("已启用" if cron_up else "未启用 ← 定时任务不会跑"))
    else:
        lines.append("crond：找不到 /etc/init.d/cron")

    if "未安装" in lines[0] and "未安装" in lines[1]:
        return "未安装（OpenWrt）"
    return "\n  ".join(lines) + "\n  （OpenWrt）"
