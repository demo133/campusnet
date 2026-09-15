"""campusnet 命令行入口。"""

from __future__ import annotations

import argparse
import contextlib
import os
import platform
import subprocess
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import __version__, autostart, carrier, wifi
from .config import (
    Config,
    _keyring_set,
    default_config_path,
    has_keyring,
)
from .detector import check_online, detect
from .providers import PROVIDERS
from .runner import Runner
from .session import Session, local_ip, local_mac

# -------------------------------------------------------------------- 输出
#: 日志级别 → (Unicode 标记, 颜色码, ASCII 降级标记)
LEVEL_MARK = {
    "debug": ("·", "90", "."),
    "info": ("•", "36", "-"),
    "ok": ("✔", "32", "v"),
    "warn": ("!", "33", "!"),
    "error": ("✘", "31", "x"),
}

#: 装饰性字符的 ASCII 替代。控制台编码编不出这些符号时用它，避免直接崩。
ASCII_TRANSLATION = {
    ord("─"): "-", ord("│"): "|", ord("✔"): "v", ord("✘"): "x",
    ord("•"): "-", ord("·"): ".", ord("★"): "*", ord("→"): "->",
    ord("…"): "...",
}


def _stream_encoding(stream) -> str:
    return getattr(stream, "encoding", None) or "ascii"


def _can_encode(stream, text: str) -> bool:
    """这个输出流编不编得出这段文本。"""
    try:
        text.encode(_stream_encoding(stream))
        return True
    except (UnicodeEncodeError, LookupError, TypeError):
        return False


def _safe_write(stream, text: str) -> None:
    """写不出去也绝不能崩。

    中文 Windows 的控制台是 cp936，显示中文没问题；但 GitHub Actions 的 Windows
    runner（cp1252）连中文都编不出来，直接 ``print`` 会抛 ``UnicodeEncodeError``
    把整个命令打挂 —— 这曾让 Windows 上三个 Python 版本的 CI 全红。
    这里做两级兜底：先原样写，不行就退到 ASCII 替代字符再写。
    """
    if stream is None:
        return
    try:
        stream.write(text)
        return
    except UnicodeEncodeError:
        pass
    enc = _stream_encoding(stream)
    with contextlib.suppress(Exception):
        stream.write(text.translate(ASCII_TRANSLATION).encode(enc, "replace").decode(enc, "replace"))


def ensure_output_encoding() -> None:
    """需要时才把标准输出切到 UTF-8。

    只在这台机器的默认编码确实编不出中文/装饰字符时才切 —— 中文 Windows 的 cp936
    本来就能显示中文，强行改 UTF-8 反而会在老终端里变乱码。
    """
    probe = "中文 ✔ ─ •"
    for stream in (sys.stdout, sys.stderr):
        if stream is None or _can_encode(stream, probe):
            continue
        with contextlib.suppress(Exception):
            # 切不了就走 _safe_write 的 ASCII 兜底
            stream.reconfigure(encoding="utf-8", errors="replace")


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    if platform.system() == "Windows":
        with contextlib.suppress(Exception):
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    return True


class Console:
    """极简控制台输出（不依赖 colorama，且在编不出中文的控制台上也不会崩）。"""

    def __init__(self, verbose: bool = False, quiet: bool = False) -> None:
        self.verbose = verbose
        self.quiet = quiet
        self.ascii_only = not _can_encode(sys.stdout, "中文 ✔ ─")
        self.color = _supports_color() and not self.ascii_only

    def _mark(self, level: str) -> str:
        unicode_mark, _color, ascii_mark = LEVEL_MARK.get(level, ("•", "0", "-"))
        return ascii_mark if self.ascii_only else unicode_mark

    def __call__(self, message: str, level: str = "info") -> None:
        if level == "debug" and not self.verbose:
            return
        if self.quiet and level in ("info", "debug"):
            return
        if self.ascii_only:
            message = message.translate(ASCII_TRANSLATION)
        mark = self._mark(level)
        if self.color:
            color = LEVEL_MARK.get(level, ("", "0", ""))[1]
            _safe_write(sys.stdout, "  \033[{}m{}\033[0m {}\n".format(color, mark, message))
        else:
            _safe_write(sys.stdout, "  {} {}\n".format(mark, message))

    def raw(self, text: str = "") -> None:
        if not self.quiet:
            _safe_write(sys.stdout, text + "\n")

    def banner(self, text: str) -> None:
        if self.quiet:
            return
        char = "-" if self.ascii_only else "─"
        line = char * max(8, min(60, len(text) + 4))
        _safe_write(sys.stdout, "\n" + line + "\n  " + text + "\n" + line + "\n")


# -------------------------------------------------------------------- 通用
#: ``--option`` 的值里，这些写法当成布尔真/假（大小写不敏感）。
_TRUE_WORDS = ("true", "yes", "on", "y")
_FALSE_WORDS = ("false", "no", "off", "n")


def parse_option(text: str) -> Tuple[str, Any]:
    """把 ``--option k=v`` 解析成 ``(k, v)``。

    **除了布尔，一律当字符串。** 这一点是刻意的，踩过坑：

    Dr.COM 的 ``para`` 字段有两个合法值 ``"00"`` 和 ``"30"``，
    它们是**协议里定义的字符串**，不是数字。如果这里把 ``30`` 解析成
    整数 ``30``，拼出来的就是 ``para=30``（看着一样），
    但 ``para=00`` 会变成 ``para=0`` —— 服务端不认，认证失败，
    而且失败信息里完全看不出是参数的锅。

    所以：只识别 ``true``/``false`` 这一组明确的布尔词，
    其余（包括数字）原样保留字符串。provider 那边需要整数会自己转换
    （``drcom.py`` 里就是 ``str(self.opt(...))``）。

    没写 ``=`` 时按 ``k=true`` 处理（``--option force`` 这种布尔开关够用）。
    """
    raw = (text or "").strip()
    if not raw:
        raise ValueError("空的 --option")
    key, sep, value = raw.partition("=")
    key = key.strip()
    if not key:
        raise ValueError("--option 缺少参数名：{!r}".format(raw))
    if not sep:
        return key, True

    value = value.strip()
    low = value.lower()
    if low in _TRUE_WORDS:
        return key, True
    if low in _FALSE_WORDS:
        return key, False
    return key, value


def apply_options(options: Dict[str, Any], pairs: Optional[List[str]]) -> List[str]:
    """把 ``--option`` 列表写进 ``options``，返回被接受的 ``k=v`` 原文。

    认不出的键**不报错** —— 这是逃生舱，用户可能想传给某个 provider 的自定义字段。
    """
    applied: List[str] = []
    for item in pairs or []:
        try:
            key, value = parse_option(item)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        options[key] = value
        applied.append("{}={}".format(key, value))
    return applied


def _load(args) -> Config:
    cfg = Config.load(getattr(args, "config", None) or default_config_path())
    if getattr(args, "username", None):
        cfg.username = args.username
    if getattr(args, "provider", None):
        cfg.provider = args.provider
    if getattr(args, "portal", None):
        cfg.portal_ip = args.portal
    if getattr(args, "timeout", None):
        cfg.timeout = args.timeout
    if getattr(args, "carrier", None):
        cfg.options["carrier"] = carrier.normalize(args.carrier)
    # --option 排在最后：它是逃生舱，应该能盖过上面那些语义化的开关
    apply_options(cfg.options, getattr(args, "option", None))
    return cfg


def _make_runner(args) -> Runner:
    return Runner(_load(args), Console(verbose=getattr(args, "verbose", False)))


# -------------------------------------------------------------------- 子命令
def cmd_status(args) -> int:
    cfg = _load(args)
    console = Console(verbose=args.verbose)
    session = Session(timeout=cfg.timeout, use_proxy=cfg.use_proxy)
    status = check_online(session)

    console.banner("campusnet 状态")
    console("网络：{}".format(status.describe()), "ok" if status.online else "warn")
    if status.portal_url:
        console("门户：{}".format(status.portal_url), "info")

    detection = detect(session, cfg, status)
    if detection.scores:
        console("认证系统：{}".format(
            ", ".join("{} {:.2f}".format(n, s) for n, s in detection.scores)), "info")
    if detection.server:
        console("服务器：{}".format(detection.server), "info")

    console("本机 IP：{}".format(local_ip() or "未知"), "info")
    console("本机 MAC：{}".format(local_mac() or "未知"), "info")
    console("账号：{}".format(cfg.username or "（未配置）"), "info")
    console("密码：{}".format(cfg.masked()), "info")

    # 运营商没设对，账号密码再对也认证不上，所以状态里要能看见
    current_carrier = str(cfg.options.get("carrier", "") or "")
    if current_carrier:
        console("运营商：{}".format(carrier.label(carrier.normalize(current_carrier))), "info")
    else:
        console("运营商：未设置（校园用户；要选运营商的话用 campusnet carrier 移动）", "info")

    # Wi-Fi 是最容易出问题的一环，状态里必须能看到
    if cfg.wifi_ssid:
        now = wifi.current_ssid()
        on_target = now == cfg.wifi_ssid
        console("校园 Wi-Fi：{}（当前 {}{}）".format(
            cfg.wifi_ssid,
            now or "未连接",
            "" if on_target else " ← 不一致，登录时会自动切回",
        ), "ok" if on_target else "warn")
    else:
        console("校园 Wi-Fi：（未配置）", "warn")

    console("配置：{}".format(cfg.path or default_config_path()), "info")
    console("自启：{}".format(autostart.status().splitlines()[0]), "info")
    # status 是「报告状态」，未联网是正常信息，不该算命令失败；
    # 需要脚本判断时用 --check。
    if getattr(args, "check", False):
        return 0 if status.online else 1
    return 0


def cmd_detect(args) -> int:
    cfg = _load(args)
    console = Console(verbose=args.verbose)
    session = Session(timeout=cfg.timeout, use_proxy=cfg.use_proxy)

    status = check_online(session)
    console.banner("门户探测")
    console("网络：{}".format(status.describe()), "ok" if status.online else "warn")

    detection = detect(session, cfg, status)
    if not detection.portal:
        if status.online:
            console("你现在已经联网，门户页面不会出现，所以探不到。", "warn")
            console("想让 campusnet 也认识你家学校的门户，可以：", "info")
            console("  1) 断开当前认证（或等下次开机会话失效）后重跑 detect；", "info")
            console("  2) 或者直接指定地址：campusnet detect --portal 10.0.0.1", "info")
        else:
            console("没能探到门户地址。自动探测也失败了，请用 --portal 手动指定，", "error")
            console("例如：campusnet detect --portal 10.0.0.1", "error")
        return 1

    console("门户地址：{}".format(detection.portal.rstrip("/")), "ok")
    console("HTTP：{}  Server：{}".format(detection.status, detection.server or "-"), "info")
    console("页面标题：{}".format(detection.title or "-"), "info")
    for key, value in detection.notes.items():
        if value:
            console("{}：{}".format(key, value), "info")

    console.raw()
    if detection.scores:
        console("指纹识别结果：", "ok")
        for name, score in detection.scores:
            console("  {:<10} {:.2f}  {}".format(name, score, PROVIDERS[name].display_name), "info")
    else:
        console("没有匹配到已知认证系统。请把上面的信息发到 issue，或改用 custom provider。", "warn")

    console.raw()
    console("提示：可以把门户地址写进配置 portal_ip，省去每次探测。", "debug")
    return 0


def _announce_options(console: "Console", args, cfg: Config) -> None:
    """把 ``--option`` 生效的内容显式打出来。

    逃生舱最危险的失败方式是「写了但没生效，看起来一切正常」——
    所以这里必须让人亲眼看到参数确实被记下了。
    """
    pairs = getattr(args, "option", None)
    if not pairs:
        return
    console("临时参数：{}".format(
        "、".join("{}={}".format(k, v) for k, v in sorted(cfg.options.items())
                  if k in {parse_option(p)[0] for p in pairs})), "info")


def cmd_login(args) -> int:
    runner = _make_runner(args)
    console = Console(verbose=args.verbose)
    _announce_options(console, args, runner.cfg)
    result = runner.ensure_online(force=args.force, limit=3)
    if result.skipped:
        console(result.message, "ok")
        return 0
    if result.ok:
        console(result.message, "ok")
        return 0
    console(result.message, "error")
    return 1


def cmd_once(args) -> int:
    """跑一次检查就走 —— 给 cron / 路由器这类「无守护进程」的场景用。

    为什么不能直接拿 ``login`` 交给 cron：

    * ``login`` 未联网时会打一堆进度信息，cron 会把这些当邮件发出来；
    * 反过来它成功时也照样输出。而 cron 任务最需要的是**安静**：
      只在出问题时才有输出，正常时一声不响。

    所以这里：已联网 → 静默退出 0；真的登录了 → 打一行结果；
    失败 → 打错误并以非零退出（cron 会因此给你发信，正好当告警）。

    退出码语义与前缀 ``0`` 统一：**成功和「已联网」都是 0**，
    只有真的没弄通才非零 —— 否则路由器上每 5 分钟一次的日志会被刷爆。
    """
    runner = _make_runner(args)
    quiet = getattr(args, "quiet", True)
    console = Console(verbose=getattr(args, "verbose", False), quiet=quiet)
    _announce_options(console, args, runner.cfg)

    result = runner.ensure_online(force=getattr(args, "force", False), limit=3)
    if result.ok:
        # 已联网时连一行都不打 —— cron 的日志空间很珍贵
        if not result.skipped:
            console(result.message, "ok")
        return 0

    # 失败必须留下痕迹，哪怕开了 -q
    loud = Console(verbose=getattr(args, "verbose", False), quiet=False)
    loud(result.message, "error")
    if result.attempts:
        loud(result.attempts[-1].short(), "debug")
    return 1


def cmd_watch(args) -> int:
    runner = _make_runner(args)
    if getattr(args, "wifi", None):
        runner.cfg.wifi_ssid = args.wifi
    console = Console(verbose=args.verbose, quiet=getattr(args, "quiet", False))
    console.banner("campusnet 守护模式")
    _announce_options(console, args, runner.cfg)
    try:
        runner.watch(
            interval_minutes=args.interval,
            warmup_seconds=getattr(args, "warmup", None),
            warmup_gap=getattr(args, "warmup_gap", None),
            retry_gap=getattr(args, "retry_gap", None),
        )
    except KeyboardInterrupt:
        return 0
    return 0


def cmd_wifi(args) -> int:
    """查看/管理 Wi-Fi：诊断、切换、以及关闭其它网络的自动连接。"""
    console = Console(verbose=args.verbose)
    cfg = _load(args)
    target = args.ssid or cfg.wifi_ssid

    action = args.action

    if action == "set":
        name = (args.ssid or "").strip()
        if not name:
            console("用法：campusnet wifi set <校园网名称>", "error")
            return 2
        cfg.wifi_ssid = name
        saved = cfg.save(cfg.path or default_config_path())
        console.banner("已设置校园 Wi-Fi")
        console("校园网：{}".format(name), "ok")
        console("配置：{}".format(saved), "info")
        console.raw()
        console("现在 campusnet login 和守护模式都会先确认连在「{}」上。".format(name), "info")
        console("建议再执行一次，把其它网络的自动连接关掉（治本）：", "info")
        console("  campusnet wifi autoconnect", "info")
        return 0

    if action == "restore":
        name = (args.ssid or "").strip()
        if not name:
            console("用法：campusnet wifi restore <名称>", "error")
            return 2
        console.banner("恢复自动连接")
        if wifi.set_autoconnect(name, enabled=True):
            console("已把「{}」改回自动连接".format(name), "ok")
            return 0
        console("没能改「{}」的设置（可能名称不对或没有权限）".format(name), "error")
        return 1

    if action == "list":
        console.banner("附近的 Wi-Fi")
        found = wifi.scan()
        if not found:
            # 扫不到不等于命令失败：CI/服务器的机器本来就没有无线网卡。
            # 返回非零会让 `run: |` 里的脚本步骤整体变红，所以这里是 0。
            console("扫描不到网络（可能没开无线网卡，或命令不可用）", "warn")
            return 0
        for item in found:
            mark = "ok" if target and item.ssid == target else "info"
            suffix = "  ← 校园网" if target and item.ssid == target else ""
            console(item.ssid + suffix, mark)
        return 0

    if action == "connect":
        if not target:
            console("没指定 Wi-Fi 名称。用 campusnet wifi connect <名称>，或先写进配置。", "error")
            return 2
        console.banner("连接 Wi-Fi")
        result = wifi.connect(target)
        console(result.message, "ok" if result.ok else "error")
        return 0 if result.ok else 1

    if action == "autoconnect":
        if not target:
            console("没指定校园 Wi-Fi 名称，无法判断该保留哪个。", "error")
            return 2
        console.banner("关闭其它 Wi-Fi 的自动连接")
        console("校园网：{}".format(target), "info")
        console("其它网络会被改成「手动连接」——开机时系统就不会抢它们了。", "info")
        console.raw()
        changed = wifi.forget_other_networks(target, logger=lambda m, lv="info": console(m, lv))
        if not changed:
            # 同上：这台机器根本没有无线网卡时不该算失败。
            # 只有「平台支持却一个都没改成」才值得报警告。
            console("没有改动任何设置（可能不支持，或本来就都对）", "warn")
            return 0
        console.raw()
        console("完成。想恢复某个网络，用：campusnet wifi restore <名称>", "info")
        return 0

    # 默认：诊断报告
    console.banner("Wi-Fi 状态")
    report = wifi.probe_report(target)
    for line in report.splitlines():
        console(line, "info")

    if not cfg.wifi_ssid:
        console.raw()
        console("提示：配置里没写 Wi-Fi 名称，所以不会自动切换网络。", "warn")
        console("加上它就能解决「开机连到别的 WiFi 后不回校园网」的问题：", "info")
        console("  campusnet wifi set CampusWiFi", "info")
    elif target and wifi.current_ssid() != target:
        console.raw()
        console("现在没连在校园网上，执行 campusnet login 会自动切回去。", "warn")
    return 0


def cmd_carrier(args) -> int:
    """查看/设置运营商。

    很多学校登录页上要先选「服务类型」（校园用户 / 校园电信 / 移动 / 联通 …），
    这一步没选对，账号密码再对也认证不上。
    """
    console = Console()
    cfg = _load(args)

    if args.name:
        code = carrier.normalize(args.name)
        cfg.options["carrier"] = code
        saved = cfg.save(cfg.path or default_config_path())
        console.banner("运营商已设置")
        console("运营商：{}".format(carrier.label(code)), "ok")
        if not carrier.is_known(code):
            console("（这是自定义值，会当作账号后缀 @{} 使用）".format(code), "warn")
        console("配置：{}".format(saved), "info")
        console.raw()
        console("下一步：campusnet login 验证一下", "info")
        return 0

    console.banner("运营商设置")
    current = str(cfg.options.get("carrier", "") or "")
    if current:
        code = carrier.normalize(current)
        console("当前：{}".format(carrier.label(code)), "ok")
    else:
        console("当前：未设置（等同于「校园用户」）", "warn")
        console.raw()
        console("如果你的学校登录时要选运营商，那这一步一定要设：", "info")

    console.raw()
    console("可选值：", "info")
    for code, text in carrier.CHOICES:
        console("  {:<10} {}".format(code, text), "info")
    console.raw()
    console("用法：campusnet carrier 移动", "info")
    console("也可以直接写自己的运营商名，会当作账号后缀处理。", "debug")
    return 0


def cmd_providers(args) -> int:
    console = Console()
    console.banner("支持的认证系统")
    for name, cls in PROVIDERS.items():
        console("{:<9} {}".format(name, cls.display_name), "info")
    console.raw()
    console("用 --provider <名字> 强制指定；默认 auto 会自动识别。", "debug")
    return 0


# -------------------------------------------------------------------- 排障
#: doctor 的每一项：(标题, 检查函数, 失败/警告时的建议)
def _check_network(cfg: Config, session: Session) -> Tuple[str, str, str]:
    status = check_online(session)
    if status.online:
        return "ok", "已联网", ""
    return "warn", status.describe(), "网络没通/没认证。先确认路由器 WAN 拿到了校园网 IP。"


def _check_portal(cfg: Config, session: Session) -> Tuple[str, str, str]:
    """门户地址还活着吗。

    这是 cron 任务失效最常见的原因：学校换了门户 IP 或换了路径。
    """
    detection = detect(session, cfg)
    if detection.portal:
        note = detection.server or "-"
        scores = "、".join("{} {:.2f}".format(n, s) for n, s in detection.scores) or "未识别"
        return "ok", "{}（Server: {}，指纹：{}）".format(
            detection.portal.rstrip("/"), note, scores), ""
    return "error", "连门户都探不到", (
        "门户地址变了，或者认证接口被关掉了。\n"
        "      手动访问一下登录页，把地址写进配置：campusnet detect --portal <地址>")


def _check_credentials(cfg: Config, session) -> Tuple[str, str, str]:
    if not cfg.username:
        return "error", "没有账号", "运行 campusnet setup 填一下"
    password = cfg.resolve_password(prompt=False)
    if not password:
        return "error", "账号 {} 有，但取不到密码".format(cfg.username), (
            "设置环境变量 CAMPUSNET_PASSWORD，或写进配置文件。\n"
            "路由器上尤其要注意：cron 的环境里没有你登录 shell 的变量！")
    return "ok", "账号 {}（密码来自 {}）".format(cfg.username, cfg.password_source or "配置"), ""


def _check_carrier(cfg: Config, session) -> Tuple[str, str, str]:
    raw = str(cfg.options.get("carrier", "") or "")
    if not raw:
        return "ok", "未设置（等同「校园用户」）", ""
    code = carrier.normalize(raw)
    if carrier.is_known(code):
        return "ok", carrier.label(code), ""
    return "warn", "自定义运营商 {}".format(code), (
        "会被当账号后缀 @{} 使用。如果学校页面上是固定选项，"
        "用 campusnet carrier 从列表里挑一个".format(code.lstrip("@")))


def _check_autostart(cfg: Config, session) -> Tuple[str, str, str]:
    text = autostart.status()
    first = (text or "").splitlines()[0] if text else "未知"
    if "未安装" in first or "未启用" in first:
        return "warn", first, "定时任务没装：campusnet autostart install --interval 5"
    return "ok", first, ""


def _check_schedule(cfg: Config, session) -> Tuple[str, str, str]:
    """定时任务本身还在跑吗。

    第二个高频失效原因：脚本文件没了（放在 /tmp 里，重启就丢），
    或者 cron 守护进程被关掉了。
    """
    system = platform.system()

    if system == "Linux":
        procd = "/etc/init.d/campusnet"
        cron_file = "/etc/crontabs/root"
        found = []
        if os.path.exists(procd):
            found.append(procd)
        if os.path.exists(cron_file):
            try:
                with open(cron_file, "r", encoding="utf-8", errors="replace") as fh:
                    body = fh.read()
                if "campusnet" in body or "drcom" in body or "eportal" in body:
                    found.append(cron_file)
            except OSError:
                pass
        # crond 活着吗（OpenWrt 上 cron 是个可开关的服务，很容易被关掉）
        cron_up = False
        if os.path.exists("/etc/init.d/cron"):
            with contextlib.suppress(Exception):
                cron_up = subprocess.run(["/etc/init.d/cron", "enabled"], check=False,
                                         capture_output=True, timeout=4).returncode == 0
        if found:
            if cron_up:
                return "ok", "已找到定时任务：{}（crond 在跑）".format("、".join(found)), ""
            return "warn", "有定时任务文件 {}，但 crond 没启用".format("、".join(found)), (
                "OpenWrt 上执行：/etc/init.d/cron enable && /etc/init.d/cron start")
        return "warn", "没找到 campusnet 的定时任务", "campusnet autostart install --interval 5"

    # macOS / Windows 交给 autostart.status 判断，这里不重复
    return "ok", "（该系统由自启配置管理，见上一项）", ""


#: 易失目录前缀 —— 这些地方重启 / 固件升级就没了。
#:
#: 抽成模块常量而不是写在函数里，是为了**可测**：测试要验证的是"这条规则的判定"，
#: 不该依赖运行平台的临时目录长什么样。
#: （踩过的坑：Linux 上 pytest 的 ``tmp_path`` 就在 ``/tmp/pytest-of-<user>/...`` 下，
#: 拿它当"持久路径"去断言判定结果是 ok，在 Linux 上必然失败、在 Windows 上必然通过 ——
#: Windows 的 tmp_path 在 ``AppData\\Local\\Temp`` 下，所以本地永远复现不出来。）
VOLATILE_PREFIXES = ("/tmp/", "/var/tmp/", "/run/")


def _check_tmp_script(cfg: Config, session) -> Tuple[str, str, str]:
    """脚本是不是放在 /tmp 之类的易失目录里。

    这条值得单独查：路由器上很多人图省事把脚本丢 /tmp，重启就没了 ——
    表现得就像是「本来好好的，最近突然失效」。
    """
    path = cfg.path or default_config_path()
    real = os.path.realpath(path) if os.path.exists(path) else path
    if any(real.startswith(prefix) for prefix in VOLATILE_PREFIXES):
        return "error", "配置在易失目录：{}".format(real), (
            "重启就丢！挪到 /etc/campusnet/config.json 或 /etc/config/ 下")
    return "ok", path, ""


DOCTOR_CHECKS = (
    ("网络", _check_network),
    ("门户", _check_portal),
    ("账号", _check_credentials),
    ("运营商", _check_carrier),
    ("自启", _check_autostart),
    ("定时任务", _check_schedule),
    ("配置位置", _check_tmp_script),
)


def cmd_doctor(args) -> int:
    """逐项体检，专治「本来好好的，突然就不自动登录了」。

    这个命令是因为一条真实反馈加的：有人在宿舍路由器上跑 OpenWrt，
    每 5 分钟访问一次认证页，一直好好的，**最近失效了**。
    这种"突然失效"几乎总能归到下面几类，所以干脆做成一条命令挨个查：

    1. 门户地址 / 接口变了（学校改版、换 IP、加加密）；
    2. 运营商或账号后缀变了（换了宽带套餐最常见的症状）；
    3. 脚本放在 /tmp 里，重启或固件升级后被清掉；
    4. cron 守护进程被关了；
    5. 密码取不到（cron 环境里没有环境变量 —— 这条最阴）。

    ``error`` 计为失败（退出码 1），``warn`` 不影响退出码。
    """
    console = Console(verbose=getattr(args, "verbose", False))
    cfg = _load(args)
    session = Session(timeout=cfg.timeout, use_proxy=cfg.use_proxy)

    console.banner("campusnet 体检")
    console("平台：{}".format(platform.platform()), "info")

    failed = 0
    for title, check in DOCTOR_CHECKS:
        try:
            level, detail, advice = check(cfg, session)
        except Exception as exc:  # 单项检查崩了不该中断整体体检
            level, detail, advice = "warn", "检查出错：{}".format(exc), ""
        console("{}：{}".format(title, detail), level)
        for line in (advice or "").splitlines():
            console("   {}".format(line), "debug" if level == "ok" else level)
        if level == "error":
            failed += 1
    console.raw()
    if failed:
        console("{} 项没过。上面列出来的就是该动手的地方。".format(failed), "error")
    else:
        console("没发现硬伤。如果还是不通，用 --verbose 看完整请求。", "ok")

    # 给一条能直接粘到路由器上跑的原始复现命令 —— 排障时最省时间
    console.raw()
    console("在路由器上不装 Python 也能手工复现一次认证：", "info")
    console("  {}".format(_raw_repro(cfg)), "info")
    return 1 if failed else 0


def _raw_repro(cfg: Config) -> str:
    """给一条 curl / uclient-fetch 的复现命令。"""
    portal = (cfg.portal_ip or "http://<门户地址>").rstrip("/")
    if "//" not in portal:
        portal = "http://" + portal
    user = cfg.username or "<学号>"
    code = carrier.normalize(str(cfg.options.get("carrier", "") or "")) or "campus"
    try:
        from .providers.drcom import CARRIERS, CODE_TO_SERVICE

        r1, r3, para, suffix = CARRIERS.get(CODE_TO_SERVICE.get(code, "校园用户"),
                                           CARRIERS["校园用户"])
    except Exception:  # 探测失败就走下面的兜底值
        r1, r3, para, suffix = "0", "0", "00", ""
    return (
        "uclient-fetch -q -O - \"{portal}/drcom/login?callback=dr1003"
        "&DDDDD={user}{suffix}&upass=<密码>&0MKKey=123456"
        "&R1={r1}&R2=&R3={r3}&R6=0&para={para}&v6ip=&v=$(date +%s)\""
    ).format(portal=portal, user=user, suffix=suffix, r1=r1, r3=r3, para=para)


def cmd_setup(args) -> int:
    console = Console()
    console.banner("campusnet 配置向导")

    path = args.config or default_config_path()
    cfg = Config.load(path)

    # 1) 账号
    default_user = cfg.username
    prompt = "上网账号（学号）"
    if default_user:
        prompt += " [{}]".format(default_user)
    try:
        entered = input("  {}：".format(prompt)).strip()
    except EOFError:
        entered = ""
    cfg.username = entered or default_user
    if not cfg.username:
        console("没有账号，取消。", "error")
        return 2

    # 2) 密码
    import getpass

    try:
        password = getpass.getpass("  密码（输入时不显示）：")
    except EOFError:
        password = ""
    if not password:
        console("没有输入密码，取消。", "error")
        return 2

    save_to = "none"
    if args.save_password:
        save_to = "config"
    elif has_keyring():
        try:
            answer = input("  检测到系统钥匙串，把密码存进去吗？[Y/n] ").strip().lower()
        except EOFError:
            answer = "y"
        if answer in ("", "y", "yes"):
            save_to = "keyring"

    if save_to == "keyring" and _keyring_set(cfg.username, password):
        cfg.password = ""
        cfg.password_source = "keyring"
        console("密码已存入系统钥匙串", "ok")
    elif save_to == "config":
        cfg.password = password
        cfg.password_source = "config"
        console("警告：密码将以明文写入 {}".format(path), "warn")
    else:
        cfg.password = ""
        console("密码未保存 —— 请用环境变量 CAMPUSNET_PASSWORD 提供", "warn")
    del password

    # 3) 探测门户
    console.raw()
    console("正在探测认证门户…", "info")
    session = Session(timeout=cfg.timeout, use_proxy=cfg.use_proxy)
    status = check_online(session)
    detection = detect(session, cfg, status)
    if detection.portal:
        console("发现门户：{}".format(detection.portal.rstrip("/")), "ok")
        cfg.portal_ip = detection.portal.rstrip("/")
        if detection.scores:
            console("认证系统：{}".format(detection.scores[0][0]), "ok")
            cfg.provider = "auto"
    else:
        console("没探测到门户，稍后可手动填 portal_ip", "warn")

    # 4) 运营商 —— 很多学校登录时要先选「校园/移动/电信/联通」
    console.raw()
    console("有些学校登录时要先选运营商（页面上的「服务类型」）。", "info")
    console("不选会影响认证，不确定就按你办宽带的那家选。", "info")
    current = str(cfg.options.get("carrier", "") or "")
    if current:
        console("当前设置：{}".format(carrier.label(carrier.normalize(current))), "debug")
    for index, (_code, text) in enumerate(carrier.CHOICES, 1):
        console("  {}. {}".format(index, text), "info")
    console("  0. 不选 / 跳过（我们学校不用选）", "info")
    try:
        picked = input("  选择 [1]：").strip()
    except EOFError:
        picked = ""
    if picked in ("0",):
        cfg.options.pop("carrier", None)
        console("已跳过运营商设置", "info")
    else:
        if picked.isdigit() and 1 <= int(picked) <= len(carrier.CHOICES):
            code = carrier.CHOICES[int(picked) - 1][0]
        elif picked:
            # 用户直接打字输入运营商名，比如「移动」或「中国移动」
            code = carrier.normalize(picked)
            if not carrier.is_known(code):
                console("没认出来，将按自定义运营商处理：{}".format(code), "warn")
        else:
            code = current_code if (current_code := carrier.normalize(current)) else "campus"
        cfg.options["carrier"] = code
        console("运营商：{}".format(carrier.label(code)), "ok")

    # 5) Wi-Fi 名称（可选，但强烈建议填）
    console.raw()
    console("校园 Wi-Fi 名称可以解决「开机连到别的网络就不回校园网」的问题。", "info")
    detected = wifi.current_ssid()
    if detected:
        console("当前连的是：{}".format(detected), "debug")
    hint = " [{}]".format(cfg.wifi_ssid) if cfg.wifi_ssid else ""
    try:
        ssid = input("  校园 Wi-Fi 名称（留空跳过）{}：".format(hint)).strip()
    except EOFError:
        ssid = ""
    if not ssid and cfg.wifi_ssid:
        ssid = cfg.wifi_ssid
    if ssid:
        cfg.wifi_ssid = ssid
        console("已记住校园网：{}".format(ssid), "ok")
    else:
        console("没填 —— 宿主机换过 Wi-Fi 后可能连不回校园网", "warn")

    cfg.path = path
    saved = cfg.save(path)
    console.raw()
    console("配置已保存：{}".format(saved), "ok")
    console("下一步：campusnet login", "info")
    return 0


def cmd_autostart(args) -> int:
    console = Console()
    cfg = _load(args)
    action = args.action
    if action == "install":
        console.banner("安装开机自启")
        try:
            console(autostart.install(cfg.path or default_config_path(), args.interval), "ok")
        except Exception as exc:  # 权限不足 / 没有 init 系统，都要给个明确报错
            console("安装失败：{}".format(exc), "error")
            return 1
        return 0
    if action == "uninstall":
        console.banner("卸载开机自启")
        console(autostart.uninstall(), "ok")
        return 0
    console.banner("开机自启状态")
    console(autostart.status(), "info")
    return 0


# -------------------------------------------------------------------- 解析
def _global_options() -> argparse.ArgumentParser:
    """全局选项，供各子命令复用（``parents=``）。

    为什么要在**两处**都挂：``campusnet -v detect`` 和
    ``campusnet detect --verbose`` 都是用户自然会打的写法。argparse 的子解析器
    是**独立**的解析器，主解析器上的 ``-v`` 在子命令之后就失效了 ——
    而项目自己的文档从头到尾写的都是后者，照着打直接报
    ``unrecognized arguments: --verbose``。与其改文档去迁就实现，
    不如让两种写法都成立。

    ⚠️ 下面每个 ``default`` 都必须是 ``argparse.SUPPRESS``：
    子解析器的默认值会在解析完子命令后**覆盖**主解析器已经取到的值，
    不抑制的话 ``campusnet -v detect`` 里的 ``-v`` 会被冲掉变回 False。
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-c", "--config", default=argparse.SUPPRESS, help="配置文件路径")
    common.add_argument(
        "-v", "--verbose", action="store_true", default=argparse.SUPPRESS,
        help="打印每个 HTTP 请求的细节",
    )
    common.add_argument(
        "--timeout", type=int, default=argparse.SUPPRESS, help="单次请求超时（秒）"
    )
    return common


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="campusnet",
        description="校园网 Portal 自动登录：Dr.COM / 深澜 Srun / 锐捷 / 华为 eportal，零依赖。",
        epilog="更多用法见 README.md",
    )
    parser.add_argument("--version", action="version", version="campusnet {}".format(__version__))
    parser.add_argument("-c", "--config", help="配置文件路径")
    parser.add_argument("-v", "--verbose", action="store_true", help="打印每个 HTTP 请求的细节")
    parser.add_argument("--timeout", type=int, help="单次请求超时（秒）")

    subs = parser.add_subparsers(dest="command")
    shared = _global_options()

    def add(name: str, help_text: str, func: Callable, **kwargs):
        sub = subs.add_parser(name, help=help_text, parents=[shared], **kwargs)
        sub.set_defaults(func=func)
        return sub

    def add_option_flag(sub) -> None:
        """逃生舱：``--option k=v`` 直接写 provider 参数。

        很多学校的门户会多出几个隐藏字段（``R7``、``wlanacname``…），
        为一个字段改代码不值得，所以留这个口子。
        """
        sub.add_argument(
            "--option", action="append", metavar="k=v", dest="option",
            help="直接写 provider 参数，可重复（如 --option r1=1 --option para=00）",
        )

    p_setup = add("setup", "交互式生成配置", cmd_setup)
    p_setup.add_argument("--save-password", action="store_true",
                         help="把密码明文写进配置文件（不推荐）")

    p_detect = add("detect", "探测门户并做指纹识别", cmd_detect)
    p_detect.add_argument("--portal", help="直接指定门户地址，跳过自动探测")
    add_option_flag(p_detect)

    p_login = add("login", "登录一次", cmd_login)
    p_login.add_argument("--force", action="store_true", help="即使已联网也重新认证")
    p_login.add_argument("--provider", help="强制使用某个认证方式")
    p_login.add_argument("--portal", help="指定门户地址")
    p_login.add_argument("--username", help="临时覆盖账号")
    p_login.add_argument("--carrier", help="运营商（如 移动 / 电信 / 联通 / 校园用户）")
    add_option_flag(p_login)

    p_watch = add("watch", "常驻守护，定时检查并自动补登录", cmd_watch)
    p_watch.add_argument("--interval", type=int, default=10, help="检查间隔（分钟，默认 10）")
    p_watch.add_argument("--warmup", type=float, default=None,
                         help="开机热身时长（秒，默认 180，0 关闭）。这段时间里会密集重试，"
                              "专门解决刚开机那几十秒连不上校园网的问题")
    p_watch.add_argument("--warmup-gap", type=float, default=None,
                         help="热身阶段的重试间隔（秒，默认 15）")
    p_watch.add_argument("--retry-gap", type=float, default=None,
                         help="某一轮没弄通时的重试间隔（秒，默认 60；联网正常时仍按 --interval）")
    p_watch.add_argument("--provider", help="强制使用某个认证方式")
    p_watch.add_argument("--wifi", help="校园 Wi-Fi 名称（覆盖配置；填了就会自动切网）")
    p_watch.add_argument("--carrier", help="运营商（如 移动 / 电信 / 联通 / 校园用户）")
    p_watch.add_argument("-q", "--quiet", action="store_true", help="静默（用于开机自启）")
    add_option_flag(p_watch)

    p_once = add("once", "跑一次检查就走（给 cron / 路由器用，等价于 login --quiet）", cmd_once)
    p_once.add_argument("--force", action="store_true", help="即使已联网也重新认证")
    p_once.add_argument("--provider", help="强制使用某个认证方式")
    p_once.add_argument("--portal", help="指定门户地址")
    p_once.add_argument("--username", help="临时覆盖账号")
    p_once.add_argument("--carrier", help="运营商（如 移动 / 电信 / 联通 / 校园用户）")
    p_once.add_argument("-q", "--quiet", action="store_true",
                        help="静默：已联网时不输出任何东西（默认开）")
    add_option_flag(p_once)

    p_wifi = add("wifi", "查看/管理 Wi-Fi（诊断、切换、关闭其它网络自动连接）", cmd_wifi)
    p_wifi.add_argument("action", nargs="?", default="status",
                        choices=["status", "list", "connect", "autoconnect", "set", "restore"],
                        help="status 诊断 / list 扫描 / connect 连接 / "
                             "autoconnect 关闭其它自动连接 / set 记住校园网 / restore 恢复")
    p_wifi.add_argument("ssid", nargs="?", default="", help="Wi-Fi 名称")

    p_status = add("status", "查看联网状态", cmd_status)
    p_status.add_argument("--check", action="store_true",
                          help="未联网时以非零退出码返回，方便写进脚本")
    add_option_flag(p_status)

    p_doctor = add("doctor", "排障：定时任务为什么失效了", cmd_doctor)
    p_doctor.add_argument("--portal", help="指定门户地址")
    p_doctor.add_argument("--username", help="临时覆盖账号")
    p_doctor.add_argument("--carrier", help="运营商")

    add("providers", "列出支持的认证系统", cmd_providers)

    p_carrier = add("carrier", "查看/设置运营商（登录前要选服务类型的学校用）", cmd_carrier)
    p_carrier.add_argument("name", nargs="?", default="",
                           help="运营商，如 移动 / 电信 / 联通 / 校园用户；留空则显示当前设置")

    p_auto = add("autostart", "管理开机自启", cmd_autostart)
    p_auto.add_argument("action", choices=["install", "uninstall", "status"])
    p_auto.add_argument("--interval", type=int, default=10, help="守护间隔（分钟）")
    p_auto.add_argument("--portal", help="门户地址")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    # 必须在解析参数之前调用：argparse 的 help 文本里也有中文，
    # 否则在编不出中文的控制台上 --help 就会崩。
    ensure_output_encoding()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        print()
        return 130
    except Exception as exc:  # CLI 顶层兜底，别把 traceback 摔用户脸上
        console = Console(verbose=getattr(args, "verbose", False))
        console("出错了：{}".format(exc), "error")
        if getattr(args, "verbose", False):
            raise
        return 1
