"""深澜 Srun Portal 认证（``/cgi-bin/srun_portal``）。

流程（三步）：

1. ``GET /cgi-bin/get_challenge`` 拿一个一次性 challenge
2. 本地算三样东西
   * ``hmd5      = md5(password + challenge)``
   * ``info      = "{SRBX1}" + srun_base64( info_json XOR challenge )``
   * ``chksum    = sha1(challenge + username + hmd5 + challenge + acid + challenge
                        + ip + challenge + n + challenge + type + challenge + info)``
3. ``GET /cgi-bin/srun_portal?action=login&...`` 带上上面三个值

注意：深澜的 base64 用的**不是**标准字母表，而是自己一套置换过的表（``SRUN_ALPHABET``）。
另外 ``password`` 字段传的是 ``{MD5}<hmd5>`` 这种带前缀的形式。

``ac_id`` 各校不同，绝大多数是 ``1``；不确定就用 ``campusnet detect`` 从页面里抠。

有些学校要先选运营商，深澜用 ``domain`` 参数表达（``@cmcc`` / ``@telecom`` /
``@unicom``）。用 ``carrier`` 选项指定即可，写法很宽松
（``移动`` / ``中国移动`` / ``cmcc`` 都认），见 ``campusnet.carrier``。
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from .. import carrier as carrier_mod
from ..session import local_ip
from .base import DetectContext, LoginResult, Provider

#: 深澜私有的 base64 字母表（64 个字符 + 填充符）
SRUN_ALPHABET = "LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA="
_STD_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_TRANS = str.maketrans(_STD_ALPHABET, SRUN_ALPHABET[:64])


# -------------------------------------------------------------------- 算法
def srun_base64(data: bytes) -> str:
    """按深澜的字母表做 base64（去掉填充）。"""
    return base64.b64encode(data).decode("ascii").translate(_TRANS).rstrip("=")


def xor_bytes(data: bytes, key: bytes) -> bytes:
    if not key:
        return data
    return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(data))


def build_hmd5(password: str, challenge: str) -> str:
    return hashlib.md5((password + challenge).encode("utf-8")).hexdigest()


def build_info(username: str, password: str, ip: str, acid: str, challenge: str,
               enc_ver: str = "srun_bx1") -> str:
    payload = {
        "username": username,
        "password": password,
        "ip": ip,
        "acid": acid,
        "enc_ver": enc_ver,
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "{SRBX1}" + srun_base64(xor_bytes(raw, challenge.encode("utf-8")))


def build_chksum(challenge: str, username: str, hmd5: str, acid: str, ip: str,
                 info: str, n: str = "200", type_: str = "1") -> str:
    joined = "".join([
        challenge, username, hmd5, challenge, acid, challenge, ip, challenge,
        n, challenge, type_, challenge, info,
    ])
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


# -------------------------------------------------------------------- Provider
class SrunProvider(Provider):
    name = "srun"
    display_name = "深澜 Srun"
    docs = "https://www.srun.com/"
    min_confidence = 0.4

    @classmethod
    def detect(cls, ctx: DetectContext) -> float:
        score = 0.0
        url = (ctx.url or "").lower()
        low = ctx.lower_text

        if "srun_portal" in low or "srun_portal" in url:
            score += 0.7
        if "cgi-bin/get_challenge" in low or "cgi-bin/srun_portal" in low:
            score += 0.6
        if "srun" in low:
            score += 0.3
        if "ac_id" in low:
            score += 0.2
        if "深澜" in ctx.text:
            score += 0.6
        if "/self/" in url or "nav_login" in url:
            score += 0.3
        return min(score, 1.0)

    def login(self, portal: str, username: str, password: str, client_ip: str = "", mac: str = "") -> LoginResult:
        ip = client_ip or local_ip()
        acid = str(self.opt("ac_id", "1"))
        n = str(self.opt("n", "200"))
        type_ = str(self.opt("type", "1"))
        os_name = str(self.opt("os", "Windows 10"))

        # 运营商：深澜用 domain 参数表达（也可以是账号后缀）。
        # 用了 domain 就不再拼后缀 —— 两者同时用会被服务端当成
        # ``账号@cmcc@cmcc``，反而认证失败。
        carrier_raw = str(self.opt("carrier", "") or "").strip()
        code = carrier_mod.normalize(carrier_raw) if carrier_raw else ""
        domain = str(self.opt("domain", "") or "").strip()
        if not domain and code:
            domain = carrier_mod.suffix_for(code).lstrip("@")
        if domain and domain.startswith("@"):
            domain = domain[1:]
        # 账号已经自带 @xxx 就不要再加 domain
        if domain and "@" in username:
            domain = ""
        errors: List[str] = []

        for origin in self.origins(portal):
            try:
                challenge = self._get_challenge(origin, username, ip)
            except Exception as exc:  # noqa: BLE001
                errors.append("{}：{}".format(origin, exc))
                continue
            if not challenge:
                errors.append("{}：拿不到 challenge".format(origin))
                continue

            hmd5 = build_hmd5(password, challenge)
            info = build_info(username, password, ip, acid, challenge)
            chksum = build_chksum(challenge, username, hmd5, acid, ip, info, n=n, type_=type_)

            query = (
                "callback=jsonp&action=login&username={u}&password={pwd}&ac_id={acid}"
                "&ip={ip}&chksum={chksum}&info={info}&n={n}&type={t}"
                "&os={os}&name={name}&double_stack=0"
            ).format(
                u=quote(username, safe=""),
                pwd=quote("{MD5}" + hmd5, safe=""),
                acid=acid,
                ip=ip,
                chksum=chksum,
                info=quote(info, safe=""),
                n=n,
                t=type_,
                os=quote(os_name, safe=""),
                name=quote(os_name, safe=""),
            )
            if domain:
                query += "&domain={}".format(quote(domain, safe=""))
            try:
                resp = self.session.get("{}/cgi-bin/srun_portal?{}".format(origin, query),
                                        headers={"Referer": origin + "/"})
            except Exception as exc:  # noqa: BLE001
                errors.append("{}：{}".format(origin, exc))
                continue

            result = self._as_result(resp, origin + "/cgi-bin/srun_portal")
            if result.ok or result.already_online:
                return result
            errors.append("{}：{}".format(origin, result.message))

        return LoginResult(
            ok=False,
            provider=self.name,
            message="登录失败。最后一次返回：{}".format(errors[-1] if errors else "无响应"),
            raw="\n".join(errors[-3:]),
        )

    # ------------------------------------------------------------ 内部
    def _get_challenge(self, origin: str, username: str, ip: str) -> str:
        url = "{}/cgi-bin/get_challenge?callback=jsonp&username={}&ip={}".format(
            origin, quote(username, safe=""), ip)
        resp = self.session.get(url, headers={"Referer": origin + "/"})
        data = self._json(resp)
        if isinstance(data, dict):
            return str(data.get("challenge") or "")
        return ""

    def _as_result(self, resp, endpoint: str) -> LoginResult:
        text = resp.text or ""
        data = self._json(resp)
        if isinstance(data, dict):
            error = str(data.get("error", "") or "")
            error_msg = str(data.get("error_msg") or data.get("msg") or "")
            if error in ("ok", "0", ""):
                return LoginResult(True, self.name, error_msg or "认证成功",
                                   endpoint=endpoint, raw=text[:600])
            if "already" in error.lower() or "在线" in error_msg:
                return LoginResult(True, self.name, error_msg or "已在线上",
                                   endpoint=endpoint, raw=text[:600], already_online=True)
            return LoginResult(False, self.name, "{} {}".format(error, error_msg).strip(),
                               endpoint=endpoint, raw=text[:600])
        return LoginResult(False, self.name, "HTTP {} 未识别响应".format(resp.status),
                           endpoint=endpoint, raw=text[:600])

    @staticmethod
    def _json(resp) -> Optional[Dict[str, Any]]:
        payload = resp.jsonp_payload
        if not payload:
            return None
        try:
            data = json.loads(payload)
        except ValueError:
            return None
        return data if isinstance(data, dict) else None
