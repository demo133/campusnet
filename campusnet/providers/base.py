"""Provider 抽象基类。

新增一所学校的支持，基本就是写一个 Provider 子类，实现两个方法：

* ``detect(ctx)`` —— 给一段门户页面打分（0~1），用来做指纹识别
* ``login(...)``  —— 真正发认证请求

具体步骤见 ``docs/providers.md``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlsplit, urlunsplit

from ..session import Response, Session


@dataclass
class DetectContext:
    """指纹识别时交给 provider 看的东西。"""

    url: str
    response: Optional[Response] = None
    text: str = ""
    headers: Dict[str, str] = field(default_factory=dict)

    @property
    def lower_text(self) -> str:
        return self.text.lower() if self.text else ""

    def has(self, *needles: str) -> bool:
        low = self.lower_text
        return all(n.lower() in low for n in needles)

    def has_any(self, *needles: str) -> bool:
        low = self.lower_text
        return any(n.lower() in low for n in needles)


@dataclass
class LoginResult:
    ok: bool
    provider: str
    message: str = ""
    endpoint: str = ""
    raw: str = ""
    already_online: bool = False

    def short(self) -> str:
        flag = "成功" if self.ok else "失败"
        return "[{}] {}：{}".format(self.provider, flag, self.message)


class Provider:
    """所有认证方式的基类。"""

    name = "base"
    display_name = "基础"
    docs = ""
    #: 指纹识别时的最低置信度，低于此值不参与排序
    min_confidence = 0.35

    def __init__(self, session: Session, options: Optional[Dict[str, Any]] = None) -> None:
        self.session = session
        self.options = dict(options or {})

    # ------------------------------------------------------------ 指纹
    @classmethod
    def detect(cls, ctx: DetectContext) -> float:
        """返回 0~1 的置信度。默认 0（认不出来）。"""
        return 0.0

    # ------------------------------------------------------------ 登录
    def login(self, portal: str, username: str, password: str, client_ip: str = "", mac: str = "") -> LoginResult:
        raise NotImplementedError

    # ------------------------------------------------------------ 小工具
    def opt(self, key: str, default: Any = None) -> Any:
        return self.options.get(key, default)

    @staticmethod
    def origins(portal: str, extra_ports: Sequence[int] = ()) -> List[str]:
        """由门户地址派生出一串候选 origin（含常见管理端口）。"""
        parts = urlsplit(portal if "//" in portal else "http://" + portal)
        host = parts.hostname or ""
        if not host:
            return []
        scheme = parts.scheme or "http"
        seen: List[str] = []
        for port in (parts.port, *extra_ports):
            netloc = host if not port else "{}:{}".format(host, port)
            candidate = urlunsplit((scheme, netloc, "", "", ""))
            if candidate not in seen:
                seen.append(candidate)
        return seen

    @staticmethod
    def ip_from_portal(portal: str) -> str:
        parts = urlsplit(portal if "//" in portal else "http://" + portal)
        return parts.hostname or ""

    @staticmethod
    def find(pattern: str, text: str, group: int = 1, default: str = "") -> str:
        match = re.search(pattern, text or "", re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(group).strip()
        return default
