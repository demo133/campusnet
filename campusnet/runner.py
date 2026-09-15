"""编排：探测 → 选择认证方式 → 登录 → 校验。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .config import Config
from .detector import Detection, NetStatus, check_online, detect, portal_candidates, provider_order
from .providers import LoginResult, get_provider
from .session import Session, local_ip, local_mac
from .wifi import WifiResult, ensure_wifi

LEVELS = ("debug", "info", "ok", "warn", "error")


def _null_log(message: str, level: str = "info") -> None:
    pass


@dataclass
class RunResult:
    ok: bool = False
    skipped: bool = False
    provider: str = ""
    message: str = ""
    status_before: Optional[NetStatus] = None
    detection: Optional[Detection] = None
    attempts: List[LoginResult] = field(default_factory=list)


class Runner:
    """把配置、HTTP 会话、provider 串起来。"""

    def __init__(self, cfg: Config, logger: Optional[Callable[[str, str], None]] = None) -> None:
        self.cfg = cfg
        self.log = logger or _null_log
        self._session: Optional[Session] = None
        #: 等 Wi-Fi 关联的超时（秒）。命令行可覆盖。
        self.wifi_timeout: float = float(cfg.options.get("wifi_timeout", 30))
        #: 开机场景的 Wi-Fi 策略 —— 只在守护模式（watch）里用。
        #: 手动 login 不启用：要给"一次尝试 + 立刻给结论"的快速反馈。
        self.wifi_attempts: int = int(cfg.options.get("wifi_attempts", 2))
        self.wifi_retry_delay: float = float(cfg.options.get("wifi_retry_delay", 5))
        self.wifi_ready_timeout: float = float(cfg.options.get("wifi_ready_timeout", 25))

    # ------------------------------------------------------------ 资源
    @property
    def session(self) -> Session:
        if self._session is None:
            self._session = Session(
                timeout=self.cfg.timeout,
                use_proxy=self.cfg.use_proxy,
                logger=lambda msg: self.log(msg, "debug"),
            )
        return self._session

    @property
    def client_ip(self) -> str:
        return local_ip()

    # ------------------------------------------------------------ 探测
    def status(self) -> NetStatus:
        hint = self.cfg.portal_ip and (self.cfg.portal_ip if "//" in self.cfg.portal_ip
                                       else "http://" + self.cfg.portal_ip + "/")
        return check_online(self.session, hint or "")

    def detect(self, status: Optional[NetStatus] = None) -> Detection:
        detection = detect(self.session, self.cfg, status)
        if detection.scores:
            self.log("识别到认证系统：{}（置信度 {:.2f}）".format(
                detection.best, detection.scores[0][1]), "ok")
        else:
            self.log("未能识别门户类型，将按通用顺序尝试", "warn")
        return detection

    # ------------------------------------------------------------ Wi-Fi
    def ensure_wifi(self, patient: bool = False) -> WifiResult:
        """把 Wi-Fi 抢回校园网。

        **必须在联网探测之前做。** 反过来就会出现这个 bug：

        连着手机热点 → 热点能上网 → 探测说「已联网」→ 直接返回，Wi-Fi 永远不切。

        所以这里的判断依据是「当前连的是不是校园网」，而不是「有没有网」。
        只有配置了 ``wifi_ssid`` 才会动手；没配就完全不影响原有行为。

        ``patient=True`` 用"开机级"的耐心：先等网卡就绪，失败还重试几次。
        开机那十几秒里无线驱动和 ``WlanSvc`` 常没准备好，一次不成很正常 ——
        这正是"有时候开机 wifi 没有自动连上"的来源。手动 ``login`` 不传它，
        保持一次尝试、快速给结论。

        注意 ``patient=False`` 时**只传原本那三个参数**：模块级 ``ensure_wifi``
        的其余参数走默认值，行为与旧版逐字一致。
        """
        kwargs = {"timeout": self.wifi_timeout, "logger": self.log}
        if patient:
            kwargs.update(
                attempts=self.wifi_attempts,
                retry_delay=self.wifi_retry_delay,
                ready_timeout=self.wifi_ready_timeout,
            )
        result = ensure_wifi(self.cfg.wifi_ssid, **kwargs)

        if not result.supported:
            self.log(result.message, "debug")
            return result
        if not result.ok:
            # 没抢到就是后续认证失败的根因，必须说清楚，别让人去查账号密码
            self.log("没能连上校园 Wi-Fi「{}」—— 网络没切过去，认证一定不会成功".format(
                self.cfg.wifi_ssid), "warn")
            return result
        if result.changed:
            # 刚换了 Wi-Fi，DHCP 还没走完，给它一点时间再探测
            delay = float(self.cfg.options.get("wifi_settle_delay", 3))
            if delay:
                time.sleep(delay)
        return result

    # ------------------------------------------------------------ 主流程
    def ensure_online(self, force: bool = False, limit: int = 3,
                      patient: bool = False, wifi_checked: bool = False) -> RunResult:
        """确认网络可用，必要时完成认证。

        ``wifi_checked=True`` 表示调用方**已经**做过 Wi-Fi 那一环了，
        这里就不再重复发一遍 ``netsh``（守护模式每轮都先自己抢一次网）。
        """
        cfg = self.cfg

        # 先抢 Wi-Fi，再判联网 —— 顺序不能反，理由见 ensure_wifi 的注释。
        if not wifi_checked:
            self.ensure_wifi(patient=patient)

        status = self.status()
        if status.online and not force:
            return RunResult(ok=True, skipped=True, message="已联网，无需认证", status_before=status)

        if status.online and force:
            self.log("当前已联网，但指定了 --force，仍要重新认证一次", "warn")

        if not cfg.username:
            return RunResult(ok=False, message="配置里没有账号，请先运行：campusnet setup", status_before=status)

        password = cfg.resolve_password(prompt=False)
        if not password:
            return RunResult(ok=False,
                             message="没有取到密码。请设置 CAMPUSNET_PASSWORD 环境变量，或用 campusnet setup 配置",
                             status_before=status)

        detection = self.detect(status)
        portal = detection.portal or (portal_candidates(cfg, status) or [""])[0]
        if not portal:
            return RunResult(ok=False, message="找不到认证门户地址，请用 --portal 指定或写入配置",
                             status_before=status, detection=detection)

        order = provider_order(cfg, detection, limit=limit)
        self.log("认证门户：{}".format(portal.rstrip("/")), "info")
        self.log("尝试顺序：{}".format(" → ".join(order)), "info")

        ip, mac = self.client_ip, local_mac()
        attempts: List[LoginResult] = []

        for name in order:
            try:
                provider = get_provider(name)(self.session, cfg.options)
            except KeyError as exc:
                self.log(str(exc), "error")
                continue
            self.log("使用 {} 登录…".format(provider.display_name), "info")
            try:
                result = provider.login(portal, cfg.username, password, ip, mac)
            except Exception as exc:  # noqa: BLE001 - 单个 provider 崩了不该中断整体
                result = LoginResult(False, name, "内部异常：{}".format(exc))
            attempts.append(result)
            self.log(result.short(), "ok" if result.ok else "warn")

            if result.already_online:
                return RunResult(ok=True, provider=name, message=result.message,
                                 status_before=status, detection=detection, attempts=attempts)

            if not result.ok:
                if result.raw:
                    self.log(result.raw, "debug")
                continue

            # 接口说成功还不够，必须联网校验通过
            if force and status.online:
                return RunResult(ok=True, provider=name, message=result.message,
                                 status_before=status, detection=detection, attempts=attempts)

            wait = float(cfg.options.get("verify_delay", 2))
            if wait:
                time.sleep(wait)
            after = self.status()
            if after.online:
                return RunResult(ok=True, provider=name, message="认证成功，网络已连通",
                                 status_before=status, detection=detection, attempts=attempts)
            self.log("接口返回成功，但联网校验未通过，继续尝试其它方式", "warn")

        message = attempts[-1].message if attempts else "没有可用的认证方式"
        return RunResult(ok=False, message=message, status_before=status,
                         detection=detection, attempts=attempts)

    def watch(self, interval_minutes: int = 10, on_event=None,
              warmup_seconds: Optional[float] = None, warmup_gap: Optional[float] = None,
              retry_gap: Optional[float] = None):
        """常驻守护：联网正常时完全安静，断了就补登录。

        分两个阶段，这是为了解决「有时候开机 wifi 没有自动连上」：

        **阶段一 · 开机热身。** 守护进程是**登录时**启动的，而这段时间
        无线驱动、``WlanSvc``、SSID 广播往往还没准备好。旧逻辑一轮不成
        就要等满 ``interval``（默认 10 分钟），用户体感就是"开机一直没网"。
        所以开头 ``warmup_seconds`` 秒内改成每 ``warmup_gap`` 秒重试一次，
        一旦联网立刻进入常规节奏。

        **阶段二 · 常规守护。** 联网正常就按 ``interval`` 检查；
        哪一轮没弄通就用 ``retry_gap`` 快速再试，而不是干等十分钟 ——
        合盖唤醒、中途被切到热点、会话超时都能很快补回来。
        """
        if warmup_seconds is None:
            warmup_seconds = float(self.cfg.options.get("wifi_warmup", 180))
        if warmup_gap is None:
            warmup_gap = float(self.cfg.options.get("wifi_warmup_gap", 15))
        if retry_gap is None:
            retry_gap = float(self.cfg.options.get("wifi_retry_gap", 60))

        self.log("守护模式启动，每 {} 分钟检查一次".format(interval_minutes), "ok")
        if self.cfg.wifi_ssid:
            self.log("已配置校园 Wi-Fi「{}」，每轮都会确认是否连在它上面".format(self.cfg.wifi_ssid), "info")

        try:
            if warmup_seconds > 0:
                self._warmup(warmup_seconds, warmup_gap, on_event)
            while True:
                online = self._watch_round_safe(on_event)
                if online:
                    time.sleep(max(30, interval_minutes * 60))
                else:
                    time.sleep(max(15.0, retry_gap))
        except KeyboardInterrupt:
            self.log("收到中断，退出守护模式", "info")
            return

    def _warmup(self, seconds: float, gap: float, on_event) -> None:
        """开机后的集中抢网阶段：一直试到联网，或超过 ``seconds``。"""
        self.log("开机热身：{} 秒内每 {} 秒试一次，直到联网".format(
            int(seconds), int(gap)), "info")
        deadline = time.time() + seconds
        while True:
            if self._watch_round_safe(on_event):
                self.log("热身阶段已联网", "ok")
                return
            remaining = deadline - time.time()
            if remaining <= 0:
                self.log("热身结束仍未联网，转为常规检查（这样也不会一直空转）", "warn")
                return
            time.sleep(max(1.0, min(gap, remaining)))

    def _watch_round_safe(self, on_event) -> bool:
        """ ``_watch_round`` 的保险版：**单轮出错绝不能让守护进程退出**。

        守护进程要活好几天，中途 provider 抛异常、系统命令抽风都是常态，
        所以每一轮单独兜住异常，出错就当"这轮没成功"，下一轮接着来。
        """
        try:
            return self._watch_round(on_event)
        except Exception as exc:  # noqa: BLE001 - 守护进程必须活到最后
            self.log("本轮检查出错：{}".format(exc), "error")
            return False

    def _watch_round(self, on_event) -> bool:
        """跑一轮：确认 Wi-Fi → 判断联网 → 必要时登录。返回是否已联网。

        Wi-Fi 这一环自己先做掉，然后告诉 ``ensure_online`` 别再重复一次 ——
        开机场景下每次重试都可能等网卡、等关联，省一次是一次。
        """
        wifi = self.ensure_wifi(patient=True)
        status = self.status()
        if status.online:
            if wifi.changed:
                self.log("已切回校园 Wi-Fi，网络正常", "ok")
            return True

        self.log("检测到网络未认证，开始自动登录…", "warn")
        result = self.ensure_online(patient=True, wifi_checked=True)
        if on_event:
            on_event(result)
        self.log(result.message, "ok" if result.ok else "error")
        return result.ok
