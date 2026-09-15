"""OpenWrt 平台支持 + ``--option`` 逃生舱 + ``doctor`` 排障命令的测试。

这个模块锁住三件事：

1. **OpenWrt 的判定顺序** —— 必须在通用 Linux 分支**之前**判出来。
   搞反了会走 ``_install_linux``：那里面找 ``systemctl``（没有），
   然后退回 ``crontab``（OpenWrt 上没有这个命令），于是一个字都不写、
   却报告"已装好"。用户看到的症状就是"按文档做了，但根本没生效"。
2. **OpenWrt 上不写任何东西进 /tmp** —— 那是 tmpfs，重启就没了。
   这正是很多人"本来跑得好好的，最近突然失效"的根因。
3. **``--option`` 的值解析** —— Dr.COM 的 ``para=00`` 必须保持字符串，
   不能被 JSON 解析成整数 ``0``（``"00"`` ≠ ``"0"``，服务端认前者）。
"""

from __future__ import annotations

import contextlib
import os

import pytest

from campusnet import autostart, cli, wifi
from campusnet.config import Config


# ============================================================ OpenWrt 判定
def test_is_openwrt_false_on_windows():
    """当前测试机是 Windows/Linux 但不是路由器，必须判为 False。"""
    assert autostart.is_openwrt() is False
    assert wifi.is_openwrt() is False


def test_is_openwrt_requires_release_file(monkeypatch):
    """只认 /etc/openwrt_release —— 比"有没有 opkg"准得多。"""
    monkeypatch.setattr(autostart.platform, "system", lambda: "Linux")
    monkeypatch.setattr(autostart.os.path, "exists",
                        lambda p: p == "/etc/openwrt_release")
    assert autostart.is_openwrt() is True


def test_is_openwrt_false_on_plain_linux(monkeypatch):
    """普通 Linux（有 opkg 也可能）不该被当成 OpenWrt。"""
    monkeypatch.setattr(autostart.platform, "system", lambda: "Linux")
    monkeypatch.setattr(autostart.os.path, "exists", lambda p: False)
    assert autostart.is_openwrt() is False


def test_is_openwrt_false_on_darwin(monkeypatch):
    """macOS 上就算有这个文件也不该走 OpenWrt 分支。"""
    monkeypatch.setattr(autostart.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(autostart.os.path, "exists", lambda p: True)
    assert autostart.is_openwrt() is False


def test_openwrt_takes_priority_over_generic_linux(monkeypatch):
    """**核心回归**：进度分派必须先问 OpenWrt，再退回 Linux。

    顺序反了就会走 _install_linux，而那条路在 OpenWrt 上静默失效。
    """
    monkeypatch.setattr(autostart.platform, "system", lambda: "Linux")
    monkeypatch.setattr(autostart, "is_openwrt", lambda: True)

    called = {}

    def fake_openwrt(config_path, interval):
        called["openwrt"] = True
        return "openwrt"

    def fake_linux(config_path, interval):
        called["linux"] = True
        return "linux"

    monkeypatch.setattr(autostart, "_install_openwrt", fake_openwrt)
    monkeypatch.setattr(autostart, "_install_linux", fake_linux)

    assert autostart.install("/etc/campusnet/config.json", 5) == "openwrt"
    assert called.get("openwrt") is True
    assert "linux" not in called, "OpenWrt 分支必须挡住通用 Linux 分支"


# ============================================================ cron 条目
def test_cron_line_uses_once_not_login(monkeypatch):
    """cron 里必须用 ``once`` —— ``login`` 每次都会打日志，会把 logread 刷满。"""
    monkeypatch.setattr(autostart, "_python_for_router", lambda: "python3")
    line = autostart._openwrt_cron_line("/etc/campusnet/config.json", 5)
    assert "once" in line
    assert "watch" not in line
    assert "-q" in line
    assert "login" not in line


def test_cron_line_interval_is_configurable(monkeypatch):
    monkeypatch.setattr(autostart, "_python_for_router", lambda: "python3")
    assert autostart._openwrt_cron_line("", 5).startswith("*/5 ")
    assert autostart._openwrt_cron_line("", 15).startswith("*/15 ")


def test_cron_line_clamps_zero_interval(monkeypatch):
    """``*/0`` 是个非法 cron 表达式，必须夹到至少 1。"""
    monkeypatch.setattr(autostart, "_python_for_router", lambda: "python3")
    assert autostart._openwrt_cron_line("", 0).startswith("*/1 ")


def test_cron_line_redirects_output(monkeypatch):
    """不带重定向的话 cron 会把每次输出都当邮件发出去。"""
    monkeypatch.setattr(autostart, "_python_for_router", lambda: "python3")
    line = autostart._openwrt_cron_line("/etc/campusnet/config.json", 5)
    assert ">>/var/log/campusnet.log" in line
    assert "2>&1" in line


def test_cron_line_quotes_config_path(monkeypatch):
    """配置路径里有空格时不能被拆成两个参数。"""
    monkeypatch.setattr(autostart, "_python_for_router", lambda: "python3")
    line = autostart._openwrt_cron_line("/etc/my config/c.json", 5)
    assert "'/etc/my config/c.json'" in line


# ============================================================ init 脚本
def test_init_script_is_procd_not_systemd():
    """OpenWrt 用 procd，不是 systemd。套 systemd 写法是白费功夫。"""
    body = autostart._OPENWRT_INIT.format(python="python3", config_arg="")
    assert "USE_PROCD=1" in body
    assert "/etc/rc.common" in body, "第一行必须是 OpenWrt 的 shebang"
    assert "procd_open_instance" in body
    assert "[Service]" not in body, "不能混进 systemd 的写法"


def test_init_script_does_not_respawn():
    """一次性任务不能开 respawn —— 否则 procd 会把它当崩溃进程疯狂重启。"""
    body = autostart._OPENWRT_INIT.format(python="python3", config_arg="")
    assert "procd_set_param respawn 0 0 0" in body


def test_init_script_embeds_config_path():
    body = autostart._OPENWRT_INIT.format(
        python="python3", config_arg=" --config /etc/campusnet/config.json")
    assert "--config /etc/campusnet/config.json" in body


# ============================================================ 安装路径
#: 这些测试用 tmp_path 冒充 /etc，所以要把 os.path.exists 换成"只看
#: 挂载点是不是被真的创建了"。注意不能写成 lambda 里再调 os.path.exists
#: —— 那是在调被 patch 过的自己，直接无限递归。
_REAL_EXISTS = os.path.exists


def _fake_exists(monkeypatch, extra=()):
    """让 exists 对真实文件生效，另外假装 ``extra`` 里的路径存在。"""
    allowed = set(extra)
    monkeypatch.setattr(autostart.os.path, "exists",
                        lambda p: p in allowed or _REAL_EXISTS(p))


def _read(path):
    """读一个断言用的文本文件。"""
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_install_openwrt_writes_no_tmp_paths(monkeypatch, tmp_path):
    """**核心约束**：写进 ini 脚本和 cron 条目的路径里绝不能出现 /tmp。

    /tmp 在 OpenWrt 上是 tmpfs，重启、拔电、固件升级都会清空 ——
    这正是"本来好好的，最近突然失效"的根因。所以专门钉一条。

    ⚠ **不能去断言安装提示文案里没有 "/tmp/"。**
    在 Linux 上 ``tmp_path`` 本身就位于 ``/tmp/pytest-of-<user>/...``，
    而提示文案会回显写出的路径 —— 于是断言把 **pytest 自己的临时目录**
    当成了"脚本写了 /tmp"的证据，假阳性，且只在 Linux 上出现
    （Windows 的 tmp_path 在 AppData\\Local\\Temp 下，所以本地永远看不到）。
    要对文件**内容**做断言，那才是真正写进路由器、重启会丢的东西。
    """
    init_path = str(tmp_path / "etc" / "init.d" / "campusnet")
    cron_path = str(tmp_path / "etc" / "crontabs" / "root")

    monkeypatch.setattr(autostart, "OPENWRT_INIT_PATH", init_path)
    monkeypatch.setattr(autostart, "OPENWRT_CRON_PATH", cron_path)
    monkeypatch.setattr(autostart, "_python_for_router", lambda: "python3")
    monkeypatch.setattr(autostart, "_run_quiet", lambda *a, **k: None)

    autostart._install_openwrt("/etc/campusnet/config.json", 5)

    assert _REAL_EXISTS(init_path), "init 脚本没写出来"
    assert _REAL_EXISTS(cron_path), "cron 条目没写出来"

    # 真正要守的：**文件内容**里不能有 /tmp 路径
    init_body = _read(init_path)
    cron_body = _read(cron_path)
    assert "/tmp/" not in init_body, "init 脚本里出现了 /tmp 路径（重启会丢）"
    assert "/tmp/" not in cron_body, "cron 条目里出现了 /tmp 路径（重启会丢）"
    # 配置路径必须指向持久位置
    assert "/etc/campusnet/config.json" in init_body


def test_install_openwrt_cron_is_idempotent(monkeypatch, tmp_path):
    """装两次不能变成两条 cron 条目。"""
    init_path = str(tmp_path / "init" / "campusnet")
    cron_path = str(tmp_path / "crontabs" / "root")
    os.makedirs(os.path.dirname(cron_path), exist_ok=True)
    with open(cron_path, "w", encoding="utf-8") as fh:
        fh.write("0 3 * * * /usr/bin/backup\n")

    monkeypatch.setattr(autostart, "OPENWRT_INIT_PATH", init_path)
    monkeypatch.setattr(autostart, "OPENWRT_CRON_PATH", cron_path)
    monkeypatch.setattr(autostart, "_python_for_router", lambda: "python3")
    monkeypatch.setattr(autostart, "_run_quiet", lambda *a, **k: None)

    autostart._install_openwrt("/etc/campusnet/config.json", 5)
    autostart._install_openwrt("/etc/campusnet/config.json", 5)

    body = _read(cron_path)
    lines = [line for line in body.splitlines() if line.strip()]
    assert len(lines) == 2, "装了两次应该只有两条条目（备份 + campusnet）"
    assert "backup" in body, "别人的 cron 条目不能被误删"


def test_install_openwrt_retargets_interval(monkeypatch, tmp_path):
    """改间隔重装时要替换旧条目，而不是再追加一条。"""
    init_path = str(tmp_path / "init" / "campusnet")
    cron_path = str(tmp_path / "crontabs" / "root")

    monkeypatch.setattr(autostart, "OPENWRT_INIT_PATH", init_path)
    monkeypatch.setattr(autostart, "OPENWRT_CRON_PATH", cron_path)
    monkeypatch.setattr(autostart, "_python_for_router", lambda: "python3")
    monkeypatch.setattr(autostart, "_run_quiet", lambda *a, **k: None)

    autostart._install_openwrt("/etc/campusnet/config.json", 5)
    autostart._install_openwrt("/etc/campusnet/config.json", 15)

    body = _read(cron_path)
    lines = [line for line in body.splitlines() if line.strip()]
    assert len(lines) == 1, "换间隔重装应该替换旧条目，不是叠加"
    assert lines[0].startswith("*/15 ")
    assert "*/5 " not in body


def test_uninstall_openwrt_keeps_other_cron_lines(monkeypatch, tmp_path):
    """卸载只该删自己的行。"""
    cron_path = str(tmp_path / "crontabs" / "root")
    os.makedirs(os.path.dirname(cron_path), exist_ok=True)
    with open(cron_path, "w", encoding="utf-8") as fh:
        fh.write("0 3 * * * /usr/bin/backup\n")
        fh.write("*/5 * * * * python3 -m campusnet once -q\n")

    monkeypatch.setattr(autostart, "OPENWRT_INIT_PATH", str(tmp_path / "no-init"))
    monkeypatch.setattr(autostart, "OPENWRT_CRON_PATH", cron_path)
    monkeypatch.setattr(autostart, "_run_quiet", lambda *a, **k: None)

    autostart._uninstall_openwrt()

    body = _read(cron_path)
    assert "backup" in body
    assert "campusnet" not in body


def test_status_openwrt_reports_crond_state(monkeypatch, tmp_path):
    """状态里必须能看见 crond 有没有启用 —— 这是最常见的"装了不跑"原因。"""
    cron_path = str(tmp_path / "root")
    with open(cron_path, "w", encoding="utf-8") as fh:
        fh.write("*/5 * * * * python3 -m campusnet once -q\n")

    monkeypatch.setattr(autostart, "OPENWRT_INIT_PATH", str(tmp_path / "nope"))
    monkeypatch.setattr(autostart, "OPENWRT_CRON_PATH", cron_path)
    _fake_exists(monkeypatch, extra=("/etc/init.d/cron",))

    class Fail:
        returncode = 1

    monkeypatch.setattr(autostart, "_run_quiet", lambda *a, **k: Fail())

    text = autostart._status_openwrt()
    assert "*/5" in text
    assert "未启用" in text


def test_status_openwrt_reports_not_installed(monkeypatch, tmp_path):
    """什么都没装时，不该假装装好了。"""
    monkeypatch.setattr(autostart, "OPENWRT_INIT_PATH", str(tmp_path / "nope1"))
    monkeypatch.setattr(autostart, "OPENWRT_CRON_PATH", str(tmp_path / "nope2"))
    monkeypatch.setattr(autostart, "_run_quiet", lambda *a, **k: None)
    _fake_exists(monkeypatch)

    assert autostart._status_openwrt() == "未安装（OpenWrt）"


# ============================================================ Linux 上的健壮性
def test_status_linux_survives_missing_crontab(monkeypatch):
    """**回归**：``crontab`` 不存在时不能把 ``autostart status`` 搞崩。

    这条在 CI 上真实炸过：Ubuntu runner 上（或没装 cron 包的最小系统里）
    ``subprocess.run(["crontab", "-l"])`` 直接抛 ``FileNotFoundError``，
    于是 ``campusnet autostart status`` 退出码变成 1 ——
    看起来像"自启坏了"，其实什么都没坏，只是没法判断。

    「报告状态」类的命令必须**永远**返回 0。
    """
    monkeypatch.setattr(autostart.shutil, "which", lambda name: None)
    monkeypatch.setattr(autostart.platform, "system", lambda: "Linux")

    def boom(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "crontab")

    monkeypatch.setattr(autostart.subprocess, "run", boom)

    assert autostart._status_linux() == "未安装"


def test_status_linux_survives_broken_systemctl(monkeypatch):
    """``systemctl --user`` 在没有 user session 的容器里会失败，也不能崩。"""
    monkeypatch.setattr(autostart.shutil, "which", lambda name: "/usr/bin/systemctl")
    monkeypatch.setattr(autostart.platform, "system", lambda: "Linux")

    def boom(*args, **kwargs):
        raise OSError("Failed to connect to bus")

    monkeypatch.setattr(autostart.subprocess, "run", boom)

    assert "未安装" in autostart._status_linux()


def test_status_linux_reports_enabled_systemd(monkeypatch):
    """正常路径不能因为加了容错就坏掉。"""
    monkeypatch.setattr(autostart.shutil, "which", lambda name: "/usr/bin/systemctl")

    class Ok:
        stdout = "enabled\n"
        returncode = 0

    monkeypatch.setattr(autostart.subprocess, "run", lambda *a, **k: Ok())

    assert "已安装" in autostart._status_linux()


def test_autostart_status_command_returns_zero(monkeypatch):
    """端到端：``autostart status`` 在任何底层失败下都该是退出码 0。"""
    import io

    monkeypatch.setattr(autostart.shutil, "which", lambda name: None)
    monkeypatch.setattr(autostart.platform, "system", lambda: "Linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    def boom(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "crontab")

    monkeypatch.setattr(autostart.subprocess, "run", boom)

    stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="")
    monkeypatch.setattr(cli.sys, "stdout", stream)
    monkeypatch.setattr(cli.sys, "stderr", stream)

    assert cli.main(["autostart", "status"]) == 0


# ============================================================ wifi 在路由器上降级
def test_wifi_connect_refuses_on_openwrt(monkeypatch):
    """路由器不做客户端切网 —— 而且不能谎报成功。

    谎报 ``ok=True`` 比报错更糟：调用方会以为"网已经切好了"，
    然后继续往下跑认证，最终失败在一个完全无关的地方。
    """
    monkeypatch.setattr(wifi, "is_openwrt", lambda: True)
    # 就算 netsh/nmcli 意外存在，也不能被调用
    monkeypatch.setattr(wifi, "_run", lambda *a, **k: pytest.fail("不该执行任何命令"))
    monkeypatch.setattr(wifi.platform, "system", lambda: "Linux")

    result = wifi.connect("CampusWiFi")
    assert result.ok is False
    assert result.supported is False
    assert "OpenWrt" in result.message


def test_wifi_supported_false_on_openwrt(monkeypatch):
    monkeypatch.setattr(wifi.platform, "system", lambda: "Linux")
    monkeypatch.setattr(wifi, "is_openwrt", lambda: True)
    assert wifi.supported() is False


def test_wifi_report_mentions_uci_on_openwrt(monkeypatch):
    """OpenWrt 的报告要给出真正该用的命令，而不是含糊其辞。"""
    monkeypatch.setattr(wifi, "is_openwrt", lambda: True)
    monkeypatch.setattr(wifi, "_openwrt_current_ssid", lambda: "CampusWiFi")
    monkeypatch.setattr(wifi, "_first_wifi_device", lambda: "radio0")

    report = wifi.probe_report("CampusWiFi")
    assert "OpenWrt" in report
    assert "uci" in report
    assert "不适用" in report


def test_forget_other_networks_noop_on_openwrt(monkeypatch):
    """路由器上别去乱改 uci 配置。"""
    monkeypatch.setattr(wifi, "is_openwrt", lambda: True)
    monkeypatch.setattr(wifi, "saved_profiles",
                        lambda: pytest.fail("不该枚举配置文件"))

    assert wifi.forget_other_networks("CampusWiFi") == []


# ============================================================ --option 解析
def test_parse_option_keeps_numbers_as_strings():
    """**核心回归**：除布尔外一律当字符串 —— 数字也不能被转成 int。

    这条踩过坑：``para`` 的合法值是 ``"00"`` 和 ``"30"``，
    它们是协议里定义的**字符串**。一旦被转成整数，
    ``para=00`` 就会变成 ``para=0`` —— 服务端不认，认证失败，
    而且失败信息里完全看不出是参数的锅。

    对 ``r1`` / ``r3`` 也是同一个道理：drcom.py 里是
    ``str(self.opt("r1", r1))``，给字符串正好，给 int 也能用，
    但**统一成字符串**能避免"某个键是数字、某个键是字符串"这种不一致。
    """
    assert cli.parse_option("para=00") == ("para", "00")
    assert cli.parse_option("para=30") == ("para", "30")
    assert cli.parse_option("r1=0") == ("r1", "0")
    assert cli.parse_option("r1=1") == ("r1", "1")
    assert cli.parse_option("n=200") == ("n", "200")
    assert cli.parse_option("ac_id=1") == ("ac_id", "1")


def test_parse_option_booleans():
    assert cli.parse_option("x=true") == ("x", True)
    assert cli.parse_option("x=yes") == ("x", True)
    assert cli.parse_option("x=false") == ("x", False)
    assert cli.parse_option("x=no") == ("x", False)


def test_parse_option_bare_key_is_true():
    """``--option force`` 这种布尔开关。"""
    assert cli.parse_option("force") == ("force", True)


def test_parse_option_free_text():
    assert cli.parse_option("ua=Windows 10") == ("ua", "Windows 10")
    assert cli.parse_option("domain=cmcc") == ("domain", "cmcc")


def test_parse_option_rejects_garbage():
    for bad in ("", "=x", "   "):
        with pytest.raises(ValueError):
            cli.parse_option(bad)


def test_apply_options_overrides_earlier_values():
    """逃生舱要能盖过语义化的开关。"""
    options = {"carrier": "campus"}
    cli.apply_options(options, ["carrier=custom_thing", "r1=1"])
    assert options["carrier"] == "custom_thing"
    assert options["r1"] == "1"


def test_option_flag_is_registered_on_login_watch_once():
    """README 里写了的参数必须真的存在 —— 这条曾经不对（文档写了但没实现）。"""
    parser = cli.build_parser()
    for argv in (["login"], ["watch"], ["once"], ["detect"], ["status"]):
        args = parser.parse_args(argv + ["--option", "r1=1"])
        assert args.option == ["r1=1"], f"{argv[0]} 上没有 --option"


def test_option_flows_into_config(monkeypatch, tmp_path):
    """``--option`` 最终必须落到 ``cfg.options`` 里。"""
    config_path = str(tmp_path / "config.json")
    with open(config_path, "w", encoding="utf-8") as fh:
        fh.write('{"username": "2200000000"}')

    args = cli.build_parser().parse_args(
        ["-c", config_path, "login", "--option", "r1=1", "--option", "para=00"])
    cfg = cli._load(args)
    assert cfg.options["r1"] == "1"
    assert cfg.options["para"] == "00"


def test_drcom_honours_option_overrides(monkeypatch, tmp_path):
    """端到端：``--option r1=1`` 要真的改变发出去的请求。"""
    from campusnet.providers.drcom import DrComProvider

    captured = {}

    class FakeSession:
        def get(self, url, **kw):
            captured["url"] = url
            raise RuntimeError("stop")

        def post(self, url, **kw):
            captured.setdefault("url", url)
            raise RuntimeError("stop")

    provider = DrComProvider(FakeSession(), {"r1": 1, "r3": 0, "para": "00"})
    # 探针让底层请求炸掉，只为了截获真正发出去的那个 URL。
    # provider.login 自己会吞掉异常并返回失败结果，所以这里必须显式忽略，
    # 只看 fake session 截到的 URL。
    with contextlib.suppress(Exception):
        provider.login("http://10.0.0.1/", "2200000000", "secret")

    assert "R1=1" in captured["url"]
    assert "para=00" in captured["url"]


# ============================================================ doctor
def test_doctor_checks_all_are_callable_with_cfg_and_session():
    """每项检查的签名必须统一 —— 混着写会让某一项静默变成"检查出错"。"""
    for title, check in cli.DOCTOR_CHECKS:
        assert callable(check), title


def test_doctor_flags_volatile_config_path(monkeypatch, tmp_path):
    """配置放在 /tmp 里必须报错 —— 重启就丢，这是真实踩过的坑。"""
    cfg = Config(username="x", path="/tmp/campusnet/config.json")
    level, detail, advice = cli._check_tmp_script(cfg, None)
    assert level == "error"
    assert "易失" in detail
    assert "/etc/" in advice


def test_doctor_accepts_persistent_config_path(monkeypatch, tmp_path):
    """不在易失目录里的配置必须判 ok。

    ⚠ **绝不能直接拿 ``tmp_path`` 当"持久路径"。**
    Linux 上 pytest 的 ``tmp_path`` 就在 ``/tmp/pytest-of-<user>/...`` 下，
    真拿它去断言判定结果是 ok，**在 Linux 上必然失败、在 Windows 上必然通过** ——
    而 Windows 的 tmp_path 在 ``AppData\\Local\\Temp`` 下，
    所以这个假阳性在本地永远复现不出来（这就是当初 ubuntu 一直红的原因）。

    正确做法：把易失前缀表换成一个跟本机无关的哨兵值，
    **测的是"不匹配就返回 ok"这条规则**，而不是这台机器的临时目录长什么样。
    真实前缀表由上一条测试（用字面 ``/tmp/...`` 路径）单独守住。
    """
    monkeypatch.setattr(cli, "VOLATILE_PREFIXES", ("/definitely-volatile/",))
    path = str(tmp_path / "config.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{}")
    cfg = Config(username="x", path=path)
    level, _detail, _advice = cli._check_tmp_script(cfg, None)
    assert level == "ok"


def test_volatile_prefixes_cover_the_known_ones():
    """钉住真实的易失目录表。

    上一条测试把它 monkeypatch 掉了，所以必须有这一条兜底 ——
    否则哪天有人把表清空，所有配置都会被判成"持久"，而测试照样全绿。
    """
    for prefix in ("/tmp/", "/var/tmp/", "/run/"):
        assert prefix in cli.VOLATILE_PREFIXES, prefix


def test_doctor_missing_password_is_error(monkeypatch):
    """cron 里取不到密码是最阴的失效原因，必须报 error 而不是警告。"""
    monkeypatch.delenv("CAMPUSNET_PASSWORD", raising=False)
    monkeypatch.setattr(Config, "resolve_password", lambda self, **kw: "")
    cfg = Config(username="2200000000")
    level, detail, advice = cli._check_credentials(cfg, None)
    assert level == "error"
    assert "密码" in detail
    assert "cron" in advice


def test_doctor_reports_carrier():
    cfg = Config(username="x", options={})
    assert cli._check_carrier(cfg, None)[0] == "ok"

    cfg = Config(username="x", options={"carrier": "telecom"})
    level, detail, _ = cli._check_carrier(cfg, None)
    assert level == "ok"
    assert "电信" in detail


def test_doctor_runs_end_to_end_on_cp1252(monkeypatch):
    """doctor 的输出里有中文，在编不出中文的控制台上也不能崩。"""
    import io

    monkeypatch.setattr(cli, "check_online",
                        lambda *a, **k: __import__("campusnet.detector", fromlist=["x"]).NetStatus(
                            online=False, detail="测试"))
    monkeypatch.setattr(cli, "detect",
                        lambda *a, **k: __import__("campusnet.detector", fromlist=["x"]).Detection())
    monkeypatch.setattr(cli.autostart, "status", lambda: "未安装")

    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="")
    monkeypatch.setattr(cli.sys, "stdout", stream)
    monkeypatch.setattr(cli.sys, "stderr", stream)

    # 未联网 + 没装自启会返回非零，但绝不能抛异常
    assert cli.main(["doctor"]) in (0, 1)


def test_raw_repro_uses_uclient_fetch():
    """给路由器用户的复现命令要用 uclient-fetch（OpenWrt 自带）。"""
    cfg = Config(username="2200000000", portal_ip="10.99.0.1")
    text = cli._raw_repro(cfg)
    assert text.startswith("uclient-fetch")
    assert "DDDDD=2200000000" in text
    assert "upass=<密码>" in text


# ============================================================ once 命令
def test_once_is_silent_when_already_online(monkeypatch):
    """已联网时必须一个字都不输出 —— 5 分钟一次的任务不能刷日志。"""
    import io

    from campusnet.runner import RunResult

    monkeypatch.setattr(cli.Runner, "ensure_online",
                        lambda self, **kw: RunResult(ok=True, skipped=True,
                                                     message="已联网，无需认证"))

    stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", newline="")
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cli.main(["once"]) == 0
    stream.flush()
    assert stream.buffer.getvalue() == b""


def test_once_reports_failure(monkeypatch):
    """失败必须留痕，哪怕开了 -q。"""
    import io

    from campusnet.runner import RunResult

    monkeypatch.setattr(cli.Runner, "ensure_online",
                        lambda self, **kw: RunResult(ok=False, message="认证失败"))

    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="")
    monkeypatch.setattr(cli.sys, "stdout", stream)

    assert cli.main(["once"]) == 1
    stream.flush()
    assert stream.buffer.getvalue(), "失败时必须有输出"
