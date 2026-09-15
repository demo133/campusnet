"""联网状态判定 + 门户探测 + 指纹识别。

判定「是否真的联网」要过两道关，缺一不可：

1. **劫持探测** —— ``generate_204`` 这类地址在真正联网时必须返回 204；
   被 Portal 拦截时会变成 302 或直接吐登录页 HTML。
2. **真实内容校验** —— 抓一个正常网页并检查内容标记。
   学校经常把探测地址加进白名单，只看第 1 关会误判为"已联网"。
"""

from __future__ import annotations

import platform
import re
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .config import Config
from .providers import DetectContext, fingerprint, rank
from .session import HttpError, Response, Session, origin

#: (地址, 期望状态码, 正文必须包含的标记)
HIJACK_PROBES: Sequence[Tuple[str, int, Optional[str]]] = (
    ("http://connect.rom.miui.com/generate_204", 204, None),
    ("http://edge.microsoft.com/captiveportal/generate_204", 204, None),
    ("http://www.msftconnecttest.com/connecttest.txt", 200, "Microsoft Connect Test"),
)

#: (地址, 正文必须包含的标记) —— 真实内容校验
CONTENT_PROBES: Sequence[Tuple[str, str]] = (
    ("http://www.baidu.com", "baidu"),
    ("http://www.qq.com", "qq"),
    ("http://www.bing.com", "bing"),
)


@dataclass
class NetStatus:
    online: bool = False
    portal_url: str = ""
    probe: str = ""
    status: int = 0
    detail: str = ""

    def describe(self) -> str:
        if self.online:
            return "已联网"
        if self.portal_url:
            return "未认证（门户：{}）".format(self.portal_url)
        return "未联网（{}）".format(self.detail or "所有探测点都不通")


@dataclass
class Detection:
    portal: str = ""
    status: int = 0
    server: str = ""
    title: str = ""
    scores: List[Tuple[str, float]] = field(default_factory=list)
    notes: Dict[str, str] = field(default_factory=dict)

    @property
    def best(self) -> str:
        return self.scores[0][0] if self.scores else ""

    def order(self, limit: int = 3) -> List[str]:
        if self.scores:
            return [name for name, _ in self.scores[:limit]]
        return []


# -------------------------------------------------------------------- 联网判定
def check_online(session: Session, portal_hint: str = "") -> NetStatus:
    """综合两关判断是否真的联网；顺便把 Portal 地址带回来。"""
    status = NetStatus()
    hijack_ok = False

    for url, expect, marker in HIJACK_PROBES:
        try:
            resp = session.get(url, timeout=5)
        except HttpError as exc:
            status.detail = str(exc)
            continue

        location = resp.location
        if location and location.startswith("http"):
            status.portal_url = location
        elif not hijack_ok and _looks_like_portal(resp):
            status.portal_url = resp.url
            status.status = resp.status

        if resp.status == expect and not location:
            if marker is None or marker.lower() in resp.text.lower():
                hijack_ok = True
                status.probe = url
                status.status = resp.status

    if not hijack_ok:
        if not status.detail:
            status.detail = "Portal 劫持探测未通过"
        if not status.portal_url and portal_hint:
            status.portal_url = portal_hint
        return status

    for url, marker in CONTENT_PROBES:
        try:
            resp = session.get(url, timeout=5)
        except HttpError:
            continue
        if resp.status == 200 and not resp.location and marker in resp.text.lower():
            status.online = True
            status.detail = ""
            return status

    status.detail = "能过劫持探测，但抓不到真实网页内容（可能被白名单）"
    return status


def _looks_like_portal(resp: Response) -> bool:
    if resp.status not in (200, 302, 301, 307, 308):
        return False
    text = resp.text.lower()
    hints = ("eportal", "srun_portal", "acsetting", "ddddd", "upass",
             "wlanuserip", "webloginid", "interface.do", "登录", "认证")
    return any(hint in text for hint in hints)


# -------------------------------------------------------------------- 门户候选
def default_gateway() -> str:
    """尽力取默认网关；取不到返回空串。

    注意：中文 Windows 的 ``ipconfig`` 输出是 GBK，必须让 subprocess 容错解码，
    否则在 reader 线程里抛 UnicodeDecodeError，stdout 会变成 None。
    """
    system = platform.system()
    if system == "Windows":
        commands = [["ipconfig"]]
    elif system == "Darwin":
        commands = [["netstat", "-rn"]]
    else:
        commands = [["ip", "route"], ["route", "-n"]]

    for command in commands:
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=4, errors="replace",
            )
            output = completed.stdout or ""
        except Exception:  # noqa: BLE001 - 取不到就用别的办法
            continue
        try:
            found = _parse_gateway(output)
        except Exception:  # noqa: BLE001
            continue
        if found:
            return found
    return ""


def _parse_gateway(text: str) -> str:
    for line in (text or "").splitlines():
        if "默认网关" in line or "Default Gateway" in line:
            match = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
            if match and match.group(1) != "0.0.0.0":
                return match.group(1)
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] == "0.0.0.0" and _is_ipv4(parts[1]):
            return parts[1]
        if len(parts) >= 2 and parts[0] == "default" and _is_ipv4(parts[1]):
            return parts[1]
    return ""


def _is_ipv4(text: str) -> bool:
    parts = (text or "").split(".")
    if len(parts) != 4:
        return False
    return all(part.isdigit() and 0 <= int(part) <= 255 for part in parts)


def portal_candidates(cfg: Config, status: NetStatus) -> List[str]:
    """门户地址候选，按可能性排序。"""
    raw: List[str] = []
    if status.portal_url:
        raw.append(status.portal_url)
    if cfg.portal_ip:
        raw.append(cfg.portal_ip)
    gateway = default_gateway()
    if gateway:
        raw.append(gateway)

    seen: List[str] = []
    for item in raw:
        base = origin(item)
        if base and base not in seen:
            seen.append(base)
    return seen


# -------------------------------------------------------------------- 探测识别
def detect(session: Session, cfg: Config, status: Optional[NetStatus] = None) -> Detection:
    """探测门户页面并做指纹识别。"""
    status = status or check_online(session, _hint(cfg))
    result = Detection()

    for candidate in portal_candidates(cfg, status):
        try:
            resp = session.get(candidate + "/", timeout=cfg.timeout)
        except HttpError:
            continue
        if resp.status >= 500:
            continue

        ctx = DetectContext(url=candidate + "/", response=resp, text=resp.text, headers=resp.headers)
        scores = fingerprint(ctx)

        result.portal = candidate + "/"
        result.status = resp.status
        result.server = resp.server
        result.title = _title(resp.text)
        result.scores = scores
        result.notes = {
            "ac_id": _find(r"ac_id\s*[=:]\s*['\"]?(\d+)", resp.text),
            "ssid": _find(r"\bssid\s*[=:]\s*['\"]?([\w\-\.]+)", resp.text),
            "vlan": _find(r"vlanid?\s*[=:]\s*['\"]?(\d+)", resp.text),
            "client_ip": _find(r"(?:v46ip|ss5|wlanuserip)\s*[=:]\s*['\"]?(\d+\.\d+\.\d+\.\d+)", resp.text),
            "portal_ip": _find(r"v4serip\s*[=:]\s*['\"]?(\d+\.\d+\.\d+\.\d+)", resp.text),
        }
        if scores:
            break

    return result


def _hint(cfg: Config) -> str:
    if not cfg.portal_ip:
        return ""
    return origin(cfg.portal_ip) + "/"


def _title(text: str) -> str:
    return _find(r"<title[^>]*>(.*?)</title>", text or "")


def _find(pattern: str, text: str) -> str:
    match = re.search(pattern, text or "", re.I | re.S)
    return match.group(1).strip() if match else ""


def provider_order(cfg: Config, detection: Detection, limit: int = 3) -> List[str]:
    """决定这次要按什么顺序尝试 provider。"""
    if cfg.provider and cfg.provider != "auto":
        return [cfg.provider]
    order = detection.order(limit) or rank(
        DetectContext(url=detection.portal, text=""), limit=limit
    )
    return order
