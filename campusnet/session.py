"""HTTP 请求层 —— 只用标准库。

为什么不直接用 requests：这个工具经常要在宿舍内网、甚至只有校园网环境的机器上安装，
依赖越少装上的概率越大。标准库够用。
"""

from __future__ import annotations

import gzip
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib
from typing import Dict, Iterable, Optional, Tuple, Union

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 8

Data = Union[None, bytes, str, Dict[str, str], Iterable[Tuple[str, str]]]


class HttpError(Exception):
    """连接层面的异常（超时、DNS 失败、拒绝连接等）。"""

    def __init__(self, message: str, url: str = "") -> None:
        super().__init__(message)
        self.url = url


class Response:
    """极简响应对象。"""

    __slots__ = ("status", "headers", "body", "url")

    def __init__(self, status: int, headers: Dict[str, str], body: bytes, url: str) -> None:
        self.status = int(status)
        self.headers = {str(k).lower(): v for k, v in headers.items()}
        self.body = body or b""
        self.url = url

    @property
    def location(self) -> Optional[str]:
        return self.headers.get("location")

    @property
    def server(self) -> str:
        return str(self.headers.get("server", ""))

    @property
    def charset(self) -> Optional[str]:
        ctype = str(self.headers.get("content-type", ""))
        if "charset=" in ctype:
            return ctype.split("charset=")[-1].split(";")[0].strip().strip('"\'')
        return None

    @property
    def text(self) -> str:
        candidates = [self.charset, "utf-8", "gb18030", "latin-1"]
        for enc in candidates:
            if not enc:
                continue
            try:
                return self.body.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return self.body.decode("utf-8", "replace")

    @property
    def jsonp_payload(self) -> Optional[str]:
        """从 JSONP 响应中取出 JSON 字符串：``dr1003({...})`` -> ``{...}``。"""
        text = self.text
        left = text.find("(")
        right = text.rfind(")")
        if left < 0 or right <= left:
            return None
        return text[left + 1:right]

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "<Response {} len={} url={}>".format(self.status, len(self.body), self.url)


class Session:
    """带连接复用与重试的简易会话。

    默认 **不使用系统代理** —— 校园网门户都是内网地址，走代理必然失败。
    """

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        use_proxy: bool = False,
        verify_tls: bool = False,
        user_agent: str = DEFAULT_UA,
        retries: int = 1,
        logger=None,
    ) -> None:
        self.timeout = timeout
        self.user_agent = user_agent
        self.retries = max(0, retries)
        self.logger = logger or (lambda *a, **k: None)

        handlers = []
        if not use_proxy:
            handlers.append(urllib.request.ProxyHandler({}))
        if not verify_tls:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            handlers.append(urllib.request.HTTPSHandler(context=ctx))
        self._opener = urllib.request.build_opener(*handlers)

    # ---------------------------------------------------------------- 请求
    def request(
        self,
        url: str,
        method: str = "GET",
        data: Data = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = None,
        allow_redirects: bool = False,
    ) -> Response:
        body = self._encode_body(data)
        hdrs = {
            "User-Agent": self.user_agent,
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "close",
        }
        if body is not None:
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
            hdrs["Content-Length"] = str(len(body))
        if headers:
            hdrs.update(headers)

        last_error: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                self.logger("  → {} {}".format(method, url))
                req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
                resp = self._opener.open(req, timeout=timeout or self.timeout)
            except urllib.error.HTTPError as exc:
                # HTTP 错误码也是有效响应（门户常靠 3xx/4xx 表达状态）
                resp = exc
            except (urllib.error.URLError, socket.timeout, ssl.SSLError, OSError) as exc:
                last_error = exc
                if attempt < self.retries:
                    continue
                raise HttpError("请求失败：{}".format(exc), url) from exc

            raw = self._read(resp)
            status = getattr(resp, "status", None) or getattr(resp, "code", 0)
            result = Response(status, dict(resp.headers.items()), raw, url)
            self.logger("  ← {} {} ({} bytes)".format(status, url, len(raw)))
            return result

        raise HttpError("请求失败：{}".format(last_error), url)

    def get(self, url: str, **kw) -> Response:
        kw.setdefault("method", "GET")
        return self.request(url, **kw)

    def post(self, url: str, data: Data = None, **kw) -> Response:
        kw.setdefault("method", "POST")
        return self.request(url, data=data, **kw)

    # ---------------------------------------------------------------- 内部
    def _encode_body(self, data: Data) -> Optional[bytes]:
        if data is None:
            return None
        if isinstance(data, bytes):
            return data
        if isinstance(data, str):
            return data.encode("utf-8")
        return urllib.parse.urlencode(data, doseq=True).encode("utf-8")

    @staticmethod
    def _read(resp) -> bytes:
        try:
            raw = resp.read()
        except Exception:  # noqa: BLE001 - 读到一半断流也要能降级
            raw = b""
        finally:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass

        encoding = ""
        try:
            encoding = (resp.headers.get("Content-Encoding") or "").lower()
        except Exception:  # noqa: BLE001
            pass

        if encoding == "gzip" and raw[:2] == b"\x1f\x8b":
            try:
                return gzip.decompress(raw)
            except Exception:  # noqa: BLE001
                return raw
        if encoding == "deflate":
            try:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
            except Exception:  # noqa: BLE001
                try:
                    return zlib.decompress(raw)
                except Exception:  # noqa: BLE001
                    return raw
        return raw


# -------------------------------------------------------------------- 本机信息
def local_ip() -> str:
    """取本机在校园网里的 IPv4。

    用 UDP connect 探测（不会真的发包），比解析 ipconfig 稳。
    """
    for target in (("8.8.8.8", 80), ("114.114.114.114", 53), ("10.255.255.255", 1)):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(0.5)
            sock.connect(target)
            return sock.getsockname()[0]
        except OSError:
            continue
        finally:
            sock.close()
    return ""


def local_mac() -> str:
    """取本机 MAC（无冒号小写）。失败时返回空串。

    注意：部分系统会返回随机化的 MAC，门户一般只把它当作辅助字段。
    """
    try:
        node = uuid.getnode()
    except Exception:  # noqa: BLE001
        return ""
    if not node:
        return ""
    return "{:012x}".format(node)


def origin(url: str) -> str:
    """把任意 URL 归一化成 ``scheme://host[:port]``。"""
    parts = urllib.parse.urlsplit(url)
    if not parts.scheme:
        parts = urllib.parse.urlsplit("http://" + url)
    netloc = parts.netloc
    return "{}://{}".format(parts.scheme or "http", netloc)
