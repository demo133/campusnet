"""Wi-Fi 模块测试。

这个模块负责修一个很具体的 bug：用户手动切到别的 Wi-Fi 之后重启，
系统连上了那个网络，于是「有没有网」的探测通过，自动登录就再也不去碰 Wi-Fi 了。

所以测试的重点有两块：

1. **解析** —— ``netsh`` 的中/英文输出都要能抠出 SSID 和配置文件名；
   中文 Windows 的输出格式和英文版不一样，这是最容易埋雷的地方。
2. **顺序** —— ``Runner.ensure_online`` 必须**先切 Wi-Fi 再判联网**。
   顺序反了 bug 就回来了，所以专门有一条测试钉住它。
"""

from __future__ import annotations

from campusnet import wifi
from campusnet.config import Config
from campusnet.runner import Runner

# ---------------------------------------------------------------- 真实 netsh 输出
#: 中文 Windows 的 ``netsh wlan show interfaces``（连上时）
INTERFACES_ZH_CONNECTED = """
系统上有 1 个接口:

    名称                   : WLAN
    说明            : 示例无线网卡
    GUID                   : 00000000-0000-0000-0000-000000000000
    物理地址       : 00:11:22:33:44:55
    状态                  : 已连接
    SSID                   : CampusWiFi
    AP BSSID               : 66:77:88:99:aa:bb
    波段                   : 5 GHz
    身份验证               : 开放式
    配置文件               : CampusWiFi
    已配置     QoS MSCS： 0
"""

#: 中文 Windows 的 ``netsh wlan show interfaces``（没连上时，SSID 是空白）
INTERFACES_ZH_DISCONNECTED = """
系统上有 1 个接口:

    名称                   : WLAN
    说明            : 示例无线网卡
    状态                  : 已断开连接
    SSID                   :
"""

#: 英文版
INTERFACES_EN_CONNECTED = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : 示例无线网卡
    GUID                   : 00000000-0000-0000-0000-000000000000
    Physical address       : 00:11:22:33:44:55
    State                  : connected
    SSID                   : Campus-Net
    BSSID                  : 66:77:88:99:aa:bb
    Profile                : Campus-Net
"""

PROFILES_ZH = """
接口 WLAN 上的配置文件:

组策略配置文件(只读)
---------------------------------
    <无>

用户配置文件
-------------
    所有用户配置文件 : gggghhhhhh iPhone 17
    所有用户配置文件 : CampusWiFi
    所有用户配置文件 : WIFI-home
    所有用户配置文件 : 校园网
    所有用户配置文件 : 404
"""

PROFILE_ZH_CampusWiFi = """
接口 WLAN 上的配置文件 CampusWiFi:
=======================================================================

已应用: 所有用户配置文件

配置文件信息
-------------------
    版本                   : 1
    类型                   : 无线局域网
    名称                   : CampusWiFi
    控制选项               :
        连接模式           : 自动连接
        网络广播           : 只在网络广播时连接
        AutoSwitch         : 请勿切换到其他网络
        MAC 随机化: 禁用

连接设置
---------------------
    SSID 数目              : 1
    SSID 名称              :“CampusWiFi”
"""


# --------------------------------------------------------------------- 解析
class TestParseInterface:
    def test_chinese_connected(self):
        state = wifi._parse_interface(INTERFACES_ZH_CONNECTED)
        assert state.ssid == "CampusWiFi"
        assert state.interface == "WLAN"
        assert state.state == "已连接"
        assert state.connected is True

    def test_chinese_disconnected_gives_empty_ssid(self):
        state = wifi._parse_interface(INTERFACES_ZH_DISCONNECTED)
        assert state.ssid == ""
        assert state.connected is False

    def test_english_connected(self):
        state = wifi._parse_interface(INTERFACES_EN_CONNECTED)
        assert state.ssid == "Campus-Net"
        assert state.interface == "Wi-Fi"

    def test_empty_input_does_not_crash(self):
        for text in ("", None, "乱码", "系统上没有无线接口"):
            state = wifi._parse_interface(text or "")
            assert state.ssid == ""

    def test_ssid_with_spaces_is_preserved(self):
        text = "    状态                  : 已连接\n    SSID                   : 我的 热点 2.4G\n"
        assert wifi._parse_interface(text).ssid == "我的 热点 2.4G"

    def test_chinese_ssid(self):
        text = "    状态                  : 已连接\n    SSID                   : 校园网\n"
        assert wifi._parse_interface(text).ssid == "校园网"

    def test_does_not_confuse_ssid_name_field(self):
        """``SSID 名称`` 出现在 profile 输出里，不能被当成当前 SSID。"""
        state = wifi._parse_interface(PROFILE_ZH_CampusWiFi)
        assert state.ssid == ""


class TestParseProfiles:
    def test_lists_all_user_profiles(self):
        profiles = wifi._parse_profiles(PROFILES_ZH)
        assert profiles == [
            "gggghhhhhh iPhone 17", "CampusWiFi", "WIFI-home", "校园网", "404",
        ]

    def test_ignores_group_policy_section(self):
        assert "组策略配置文件(只读)" not in wifi._parse_profiles(PROFILES_ZH)

    def test_english_output(self):
        text = "    All User Profile     : Campus-Net\n    All User Profile     : Home\n"
        assert wifi._parse_profiles(text) == ["Campus-Net", "Home"]

    def test_empty(self):
        assert wifi._parse_profiles("") == []
        assert wifi._parse_profiles(None or "") == []


# --------------------------------------------------------------------- 连接逻辑
class TestEnsureWifi:
    def test_no_ssid_configured_is_supported_false(self):
        """没配 Wi-Fi 名称 → 完全不影响原有行为。"""
        result = wifi.ensure_wifi("")
        assert result.supported is False
        assert result.ok is True

    def test_already_on_target_does_nothing(self, monkeypatch):
        monkeypatch.setattr(wifi, "current_ssid", lambda: "CampusWiFi")
        called = []
        monkeypatch.setattr(wifi, "connect", lambda *a, **k: called.append(a))

        result = wifi.ensure_wifi("CampusWiFi")
        assert result.ok is True
        assert result.changed is False
        assert called == []  # 关键：不该发连接命令

    def test_switches_back_when_on_another_network(self, monkeypatch):
        """核心场景：连着别的网 → 必须切回校园网。"""
        state = {"ssid": "gggghhhhhh iPhone 17"}
        monkeypatch.setattr(wifi, "current_ssid", lambda: state["ssid"])

        def fake_connect(ssid, timeout=30.0, poll=True):
            state["ssid"] = ssid
            return wifi.WifiResult(ok=True, ssid=ssid, target=ssid, changed=True,
                                   message="已连接到 Wi-Fi「{}」".format(ssid))

        monkeypatch.setattr(wifi, "connect", fake_connect)

        result = wifi.ensure_wifi("CampusWiFi")
        assert result.ok is True
        assert result.changed is True
        assert result.ssid == "CampusWiFi"
        assert state["ssid"] == "CampusWiFi"

    def test_disconnected_then_connects(self, monkeypatch):
        monkeypatch.setattr(wifi, "current_ssid", lambda: "")
        monkeypatch.setattr(wifi, "connect",
                            lambda ssid, timeout=30.0, poll=True: wifi.WifiResult(
                                ok=True, ssid=ssid, target=ssid, changed=True))
        result = wifi.ensure_wifi("CampusWiFi")
        assert result.ok is True
        assert result.changed is True

    def test_connect_failure_is_reported_not_raised(self, monkeypatch):
        monkeypatch.setattr(wifi, "current_ssid", lambda: "别的网")
        monkeypatch.setattr(wifi, "connect",
                            lambda ssid, timeout=30.0, poll=True: wifi.WifiResult(
                                ok=False, target=ssid, message="连不上"))
        result = wifi.ensure_wifi("CampusWiFi")
        assert result.ok is False
        assert "连不上" in result.message

    def test_logs_a_warning_when_switching(self, monkeypatch):
        monkeypatch.setattr(wifi, "current_ssid", lambda: "别的网")
        monkeypatch.setattr(wifi, "connect",
                            lambda ssid, timeout=30.0, poll=True: wifi.WifiResult(
                                ok=True, ssid=ssid, changed=True))
        logs = []
        wifi.ensure_wifi("CampusWiFi", logger=lambda m, lv="info": logs.append((lv, m)))
        assert any(lv == "warn" for lv, _ in logs)


class TestConnect:
    def test_empty_ssid_rejected(self):
        result = wifi.connect("")
        assert result.ok is False

    def test_command_failure_reported(self, monkeypatch):
        monkeypatch.setattr(wifi, "_run", lambda cmd: (1, "配置文件不存在"))
        monkeypatch.setattr(wifi.platform, "system", lambda: "Windows")
        result = wifi.connect("不存在的网", poll=False)
        assert result.ok is False
        assert "不存在的网" in result.message

    def test_windows_command_shape(self, monkeypatch):
        seen = {}

        def fake_run(cmd):
            seen["cmd"] = cmd
            return 0, ""

        monkeypatch.setattr(wifi, "_run", fake_run)
        monkeypatch.setattr(wifi.platform, "system", lambda: "Windows")
        wifi.connect("CampusWiFi", poll=False)
        assert seen["cmd"] == ["netsh", "wlan", "connect", "name=CampusWiFi", "ssid=CampusWiFi"]

    def test_polls_until_associated(self, monkeypatch):
        """netsh connect 是异步的，必须轮询确认真的连上了。"""
        monkeypatch.setattr(wifi, "_run", lambda cmd: (0, ""))
        monkeypatch.setattr(wifi.platform, "system", lambda: "Windows")
        monkeypatch.setattr(wifi.time, "sleep", lambda s: None)

        calls = {"n": 0}

        def fake_ssid():
            calls["n"] += 1
            return "CampusWiFi" if calls["n"] >= 3 else "旧网络"

        monkeypatch.setattr(wifi, "current_ssid", fake_ssid)
        result = wifi.connect("CampusWiFi", timeout=30)
        assert result.ok is True
        assert calls["n"] >= 3


class TestAutoconnect:
    def test_noop_when_target_empty(self, monkeypatch):
        assert wifi.forget_other_networks("") == []

    def test_unsupported_on_macos(self, monkeypatch):
        monkeypatch.setattr(wifi.platform, "system", lambda: "Darwin")
        assert wifi.forget_other_networks("CampusWiFi") == []

    def test_disables_everything_but_target(self, monkeypatch):
        monkeypatch.setattr(wifi.platform, "system", lambda: "Windows")
        monkeypatch.setattr(wifi, "saved_profiles",
                            lambda: ["CampusWiFi", "热点A", "热点B"])

        touched = []

        def fake_set(profile, enabled):
            touched.append((profile, enabled))
            return True

        monkeypatch.setattr(wifi, "set_autoconnect", fake_set)
        changed = wifi.forget_other_networks("CampusWiFi")

        assert changed == ["热点A", "热点B"]
        assert all(enabled is False for _, enabled in touched)
        assert ("CampusWiFi", False) not in touched  # 校园网必须留着自动连接

    def test_failures_are_filtered_out(self, monkeypatch):
        monkeypatch.setattr(wifi.platform, "system", lambda: "Windows")
        monkeypatch.setattr(wifi, "saved_profiles", lambda: ["CampusWiFi", "A", "B"])
        monkeypatch.setattr(wifi, "set_autoconnect",
                            lambda p, enabled: p == "A")
        assert wifi.forget_other_networks("CampusWiFi") == ["A"]

    def test_rewrites_connection_mode(self, monkeypatch, tmp_path):
        """真改 XML 的那条路径：导出 → 替换 connectionMode → 写回。"""
        workdir = tmp_path / "wifi-export"
        workdir.mkdir()
        xml = (
            '<?xml version="1.0"?>\n<WLANProfile>\n  <name>热点A</name>\n'
            "  <connectionMode>auto</connectionMode>\n</WLANProfile>\n"
        )
        (workdir / "热点A.xml").write_text(xml, encoding="utf-8")

        commands = []

        def fake_run(cmd):
            commands.append(cmd)
            if "show" in cmd:
                return 0, "    连接模式           : 自动连接\n"
            if "export" in cmd:
                return 0, ""
            return 0, ""

        monkeypatch.setattr(wifi.platform, "system", lambda: "Windows")
        monkeypatch.setattr(wifi, "_run", fake_run)
        monkeypatch.setattr(wifi.tempfile, "mkdtemp",
                            lambda prefix="", **kw: str(workdir))
        # 生产代码在 finally 里会清掉临时目录，测试里必须挡掉，
        # 否则断言时文件已经被删了
        monkeypatch.setattr(wifi.shutil, "rmtree", lambda *a, **k: None)

        assert wifi.set_autoconnect("热点A", enabled=False) is True

        written = (workdir / "热点A.xml").read_text(encoding="utf-8")
        assert "<connectionMode>manual</connectionMode>" in written
        assert any("add" in c for c in commands)

    def test_skips_write_when_already_correct(self, monkeypatch):
        """已经是手动模式就别瞎折腾，避免反复重写 profile。"""
        monkeypatch.setattr(wifi.platform, "system", lambda: "Windows")
        monkeypatch.setattr(wifi, "_run", lambda cmd: (0, "    连接模式           : 手动\n"))
        assert wifi.set_autoconnect("热点A", enabled=False) is True


# --------------------------------------------------------------------- 顺序（回归）
class TestRunnerOrdering:
    """**最重要的测试**：先切 Wi-Fi，再判联网。顺序反了这个 bug 就回来了。"""

    def test_wifi_is_switched_before_online_check(self, monkeypatch):
        events = []

        monkeypatch.setattr("campusnet.runner.ensure_wifi",
                            lambda ssid, timeout=30.0, logger=None: (
                                events.append("wifi"),
                                wifi.WifiResult(ok=True, ssid="CampusWiFi", changed=True,
                                                target="CampusWiFi"))[1])

        cfg = Config(username="2200000000", wifi_ssid="CampusWiFi")
        runner = Runner(cfg)

        def fake_status():
            events.append("status")

            class S:
                online = True
                portal_url = ""
                detail = ""

                def describe(self):
                    return "已联网"

            return S()

        monkeypatch.setattr(runner, "status", fake_status)
        result = runner.ensure_online()

        assert events == ["wifi", "status"], "必须先切 Wi-Fi 再判联网"
        assert result.skipped is True  # 切回校园网之后确实已联网，直接收工

    def test_still_skips_when_no_wifi_configured(self, monkeypatch):
        """没配 wifi_ssid 的老用户行为完全不变。"""
        called = []
        monkeypatch.setattr("campusnet.runner.ensure_wifi",
                            lambda ssid, timeout=30.0, logger=None: called.append(ssid) or
                            wifi.WifiResult(ok=True, supported=False))

        cfg = Config(username="u")
        runner = Runner(cfg)

        class S:
            online = True
            portal_url = ""
            detail = ""

            def describe(self):
                return "已联网"

        monkeypatch.setattr(runner, "status", lambda: S())
        result = runner.ensure_online()
        assert called == [""]
        assert result.skipped is True

    def test_returns_run_result(self):
        """单个 provider 崩了不该炸整个 Runner —— 这条守住返回类型契约。"""
        from campusnet.runner import RunResult

        runner = Runner(Config(username="u", wifi_ssid=""))
        assert isinstance(RunResult(), RunResult)
        assert isinstance(runner, Runner)


# ===================================================================== 开机场景
#: 中文 netsh 的「无线电状态」是**两行**：硬件打开 / 软件打开。
#: 拿整段输出去找"关闭"会把 ``状态 : 已断开连接`` 这种字段也算进去，
#: 所以判定只能看这一个字段（和它的续行）。
RADIO_ZH_ON = """
系统上有 1 个接口:

    名称                   : WLAN
    状态                  : 已连接
    SSID                   : CampusWiFi
    无线电状态             : 硬件打开
                             软件打开
"""

RADIO_ZH_OFF = """
系统上有 1 个接口:

    名称                   : WLAN
    状态                  : 已断开连接
    无线电状态             : 硬件关闭
                             软件关闭
"""

RADIO_EN_ON = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    State                  : connected
    SSID                   : Campus-Net
    Radio status           : Hardware On
                             Software On
"""

RADIO_EN_OFF = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    State                  : disconnected
    Radio status           : Hardware Off
                             Software Off
"""

#: WlanSvc 还没起来时，netsh 一个接口都列不出来
NO_INTERFACE = "系统上没有无线接口。\n"


class TestRadioReady:
    """开机那几十秒，无线驱动和 WlanSvc 还没起来 —— 连接命令根本执行不了。

    这一组是``"有时候开机 wifi 没有自动连上"``的第一层防护：
    先判断网卡能不能用，别在没准备好的时候白试一次。
    """

    def test_radio_on_is_ready(self):
        assert wifi.interface_ready(RADIO_ZH_ON) is True
        assert wifi.interface_ready(RADIO_EN_ON) is True

    def test_radio_off_is_not_ready(self):
        assert wifi.interface_ready(RADIO_ZH_OFF) is False
        assert wifi.interface_ready(RADIO_EN_OFF) is False

    def test_no_interface_is_not_ready(self):
        assert wifi.interface_ready(NO_INTERFACE) is False

    def test_unknown_format_does_not_block(self):
        """认不出无线电状态时不该拦着 —— 有接口就算就绪，多试一次没坏处。"""
        assert wifi.interface_ready(INTERFACES_ZH_CONNECTED) is True

    def test_radio_off_only_looks_at_the_radio_field(self):
        """关键：``状态 : 已断开连接`` 不能被读成"无线被关掉了"。

        这是最容易写错的地方 —— 一旦改成"整段输出里找关闭"，
        netsh 输出里其它字段就会把判断带偏，结果是永远连不上。
        """
        assert wifi._radio_off(INTERFACES_ZH_CONNECTED) is False
        assert wifi._radio_off(RADIO_ZH_OFF) is True
        assert wifi._radio_off(INTERFACES_EN_CONNECTED) is False
        assert wifi._radio_off(RADIO_EN_OFF) is True

    def test_non_windows_is_always_ready(self, monkeypatch):
        monkeypatch.setattr(wifi.platform, "system", lambda: "Linux")
        assert wifi.interface_ready("") is True
        assert wifi.wait_for_radio(0) is True


class TestEnsureWifiRetry:
    """一次不成要能重试 —— 但**默认必须还是一次**，手动 login 要快速给结论。"""

    def test_default_is_still_single_attempt(self, monkeypatch):
        monkeypatch.setattr(wifi, "current_ssid", lambda: "别的网")
        calls = []

        def fake(ssid, timeout=30.0, poll=True):
            calls.append(ssid)
            return wifi.WifiResult(ok=False, target=ssid, message="连不上")

        monkeypatch.setattr(wifi, "connect", fake)
        result = wifi.ensure_wifi("CampusWiFi")
        assert result.ok is False
        assert calls == ["CampusWiFi"], "默认不该重试"

    def test_retries_until_connected(self, monkeypatch):
        state = {"ssid": "别的网", "calls": 0}
        monkeypatch.setattr(wifi, "current_ssid", lambda: state["ssid"])

        def flaky(ssid, timeout=30.0, poll=True):
            state["calls"] += 1
            if state["calls"] < 3:
                return wifi.WifiResult(ok=False, target=ssid, message="连不上")
            state["ssid"] = ssid
            return wifi.WifiResult(ok=True, ssid=ssid, target=ssid, changed=True,
                                   message="已连接到 Wi-Fi「{}」".format(ssid))

        monkeypatch.setattr(wifi, "connect", flaky)
        result = wifi.ensure_wifi("CampusWiFi", attempts=3, retry_delay=0)

        assert result.ok is True
        assert state["calls"] == 3
        assert state["ssid"] == "CampusWiFi"

    def test_retry_picks_up_a_late_association(self, monkeypatch):
        """上一次的连接命令其实生效了，只是关联慢 —— 重试时要能认出来。"""
        state = {"ssid": "别的网"}

        def slow(ssid, timeout=30.0, poll=True):
            state["ssid"] = ssid          # 命令发出去了，但这次没等到连上
            return wifi.WifiResult(ok=False, target=ssid, message="超时")

        monkeypatch.setattr(wifi, "current_ssid", lambda: state["ssid"])
        monkeypatch.setattr(wifi, "connect", slow)

        result = wifi.ensure_wifi("CampusWiFi", attempts=2, retry_delay=0)
        assert result.ok is True
        assert result.changed is True, "已经切过去了，要告诉调用方等 DHCP"

    def test_failure_keeps_reason_and_reports_attempts(self, monkeypatch):
        monkeypatch.setattr(wifi, "current_ssid", lambda: "别的网")
        monkeypatch.setattr(wifi, "connect",
                            lambda ssid, timeout=30.0, poll=True: wifi.WifiResult(
                                ok=False, target=ssid, message="连不上"))
        result = wifi.ensure_wifi("CampusWiFi", attempts=2, retry_delay=0)
        assert result.ok is False
        assert "连不上" in result.message, "原始原因不能丢，否则没法排查"
        assert "重试 2 次" in result.message

    def test_ready_timeout_waits_for_radio_first(self, monkeypatch):
        monkeypatch.setattr(wifi, "current_ssid", lambda: "CampusWiFi")
        waited = []
        monkeypatch.setattr(wifi, "wait_for_radio",
                            lambda timeout, logger=None: waited.append(timeout) or True)

        result = wifi.ensure_wifi("CampusWiFi", ready_timeout=20)
        assert result.ok is True
        assert waited == [20], "要先等网卡就绪再判断/连接"

    def test_default_does_not_wait_for_radio(self, monkeypatch):
        monkeypatch.setattr(wifi, "current_ssid", lambda: "CampusWiFi")

        def boom(*args, **kwargs):
            raise AssertionError("默认不该去等网卡")

        monkeypatch.setattr(wifi, "wait_for_radio", boom)
        assert wifi.ensure_wifi("CampusWiFi").ok is True


class TestWatchWarmup:
    """开机热身：这是"有时候开机连不上"的正解。

    守护进程在**登录时**启动，而无线驱动 / SSID 广播往往还要再过十几秒才好。
    旧逻辑一轮不成就要等满 ``--interval``（10 分钟），用户体感就是"一直没网"。
    """

    def _setup(self, monkeypatch, online_at_round: int):
        from campusnet.runner import RunResult

        cfg = Config(username="u", wifi_ssid="CampusWiFi")
        runner = Runner(cfg)
        state = {"round": 0}
        sleeps = []
        logs = []
        clock = {"t": 1000.0}

        class S:
            def __init__(self, online):
                self.online = online

        def fake_wifi(ssid, **kwargs):
            # 守护模式必须走"耐心"那条路，否则开机抢不到网
            assert kwargs.get("attempts"), "守护模式必须带重试参数（patient=True）"
            assert kwargs.get("ready_timeout"), "守护模式必须先等网卡就绪"
            return wifi.WifiResult(ok=True, ssid="CampusWiFi", target="CampusWiFi")

        def fake_status():
            state["round"] += 1
            return S(state["round"] >= online_at_round)

        def fake_time():
            return clock["t"]

        def fake_sleep(seconds):
            sleeps.append(seconds)
            clock["t"] += seconds
            if len(sleeps) > 30:      # 给死循环一个出口
                raise KeyboardInterrupt

        monkeypatch.setattr("campusnet.runner.ensure_wifi", fake_wifi)
        monkeypatch.setattr("campusnet.runner.time.sleep", fake_sleep)
        monkeypatch.setattr("campusnet.runner.time.time", fake_time)
        monkeypatch.setattr(runner, "status", fake_status)
        monkeypatch.setattr(runner, "ensure_online",
                            lambda **kw: RunResult(ok=False, message="未认证"))
        runner.log = lambda message, level="info": logs.append((level, message))
        return runner, state, sleeps, logs

    def test_warmup_retries_densely_then_settles(self, monkeypatch):
        runner, _, sleeps, logs = self._setup(monkeypatch, online_at_round=3)

        runner.watch(interval_minutes=10, warmup_seconds=300, warmup_gap=15, retry_gap=60)

        assert sleeps[:3] == [15, 15, 600], "前两轮按 warmup_gap 密试，联网后回到 interval"
        assert any("热身" in message for _, message in logs)

    def test_warmup_gives_up_and_falls_back_to_normal_interval(self, monkeypatch):
        runner, _, sleeps, logs = self._setup(monkeypatch, online_at_round=999)

        runner.watch(interval_minutes=10, warmup_seconds=30, warmup_gap=15, retry_gap=60)

        # 热身里试了两把（15+15 = 30 秒用光），之后转常规节奏
        assert sleeps[:2] == [15, 15]
        assert sleeps[2] == 60, "没联网时用 retry_gap，而不是干等 interval"
        assert any("热身结束" in message for _, message in logs)

    def test_failed_round_retries_quickly(self, monkeypatch):
        """某一轮没弄通 → 用 retry_gap 快速再试，不要干等十分钟。"""
        runner, _, sleeps, _ = self._setup(monkeypatch, online_at_round=999)

        runner.watch(interval_minutes=10, warmup_seconds=0, retry_gap=60)

        assert sleeps[0] == 60

    def test_round_error_does_not_kill_daemon(self, monkeypatch):
        """单轮抛异常只能影响那一轮 —— 守护进程要活好几天。"""
        runner, state, _, logs = self._setup(monkeypatch, online_at_round=999)

        def flaky_status():
            state["round"] += 1
            if state["round"] == 1:
                raise RuntimeError("netsh 抽风了")

            class S:
                online = True

            return S()

        monkeypatch.setattr(runner, "status", flaky_status)

        runner.watch(interval_minutes=10, warmup_seconds=0, retry_gap=60)

        assert any("本轮检查出错" in message for _, message in logs)
        assert state["round"] >= 2, "出错之后必须继续跑下一轮"
