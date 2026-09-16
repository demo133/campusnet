"""新版 eportal 门户认证（``/eportal/portal/login``，JSONP 回调）。

较新的 eportal 部署不再提供 ``ACSetting`` / ``InterFace.do`` 这两个老接口，
改用一条 **GET** 查询串接口：

``GET /eportal/portal/login?callback=dr1003&login_method=1&user_account=...``

全部参数都在查询串里，典型字段：

* ``callback`` —— JSONP 回调名（``dr1003``），响应是 ``dr1003({"result":1,...})``
* ``login_method`` —— 固定 ``1``
* ``user_account`` / ``user_password`` —— 账号密码，**明文**
* ``wlan_user_ip`` —— 本机在校园网里的 IP；``wlan_user_mac`` 传全零即可
* ``jsVersion`` —— 门户脚本版本号（``4.2.1``），服务端只做兼容性检查

与老接口最大的差异在**运营商选择**：页面上那个运营商下拉框不产生独立字段，
而是把运营商**拼成账号后缀**（``@cmcc`` / ``@unicom`` / ``@telecom``，
校园网账号不带后缀）。``carrier`` 选项由 :mod:`campusnet.carrier` 翻译成后缀。

门户常挂在 **801** 端口（和经典 eportal 相同），所以 origin 候选里带上
801 / 803 两个端口。
"""

from __future__ import annotations

import json
import urllib.parse
from typing import List, Optional

from .. import carrier as carrier_mod
from ..session import local_ip
from .base import DetectContext, LoginResult, Provider

CALLBACK = "dr1003"
JS_VERSION = "4.2.1"
#: 缓存穿透参数，抓包里见过 5911，服务端不校验取值
CACHE_BUSTER = "5911"

_ALREADY_HINTS = ("已在线", "已经在线", "重复认证", "重复上线", "already online", "already")


class EportalPortalProvider(Provider):
    name = "eportal_portal"
    display_name = "ePortal 新版（portal/login）"
    min_confidence = 0.4

    # ------------------------------------------------------------ 指纹
    @classmethod
    def detect(cls, ctx: DetectContext) -> float:
        score = 0.0
        low = ctx.lower_text
        url = (ctx.url or "").lower()

        if "portal/login" in url or "portal/login" in low:
            score += 0.6
        if "dr1003" in low:
            score += 0.55
        if "login_method" in low:
            score += 0.3
        if "jsversion" in low or "jsversion=4" in url:
            score += 0.25
        if "user_account" in low:
            score += 0.3
        if "wlanuserip" in low or "wlan_user_ip" in low:
            score += 0.15
        if "/eportal/" in url:
            score += 0.15
        return min(score, 1.0)

    # ------------------------------------------------------------ 登录
    def login(self, portal: str, username: str, password: str, client_ip: str = "", mac: str = "") -> LoginResult:
        ip = client_ip or local_ip()
        account = self._account_with_suffix(username)
        errors: List[str] = []

        for o in self.origins(portal, extra_ports=(801, 803)):
            query = urllib.parse.urlencode({
                "callback": CALLBACK,
                "login_method": "1",
                "user_account": account,
                "user_password": password,
                "wlan_user_ip": ip,
                "wlan_user_ipv6": "",
                "wlan_user_mac": "000000000000",
                "wlan_ac_ip": "",
                "wlan_ac_name": "",
                "jsVersion": JS_VERSION,
                "terminal_type": "1",
                "lang": "zh-cn",
                "v": str(self.opt("v", CACHE_BUSTER)),
            })
            url = "{}/eportal/portal/login?{}".format(o, query)
            try:
                resp = self.session.get(url, headers={"Referer": o + "/"})
            except Exception as exc:  # noqa: BLE001
                errors.append("{}：{}".format(o, exc))
                continue

            result = self._as_result(resp, url)
            if result.ok or result.already_online:
                return result
            errors.append("{}：{}".format(o, result.message))

        return LoginResult(
            ok=False,
            provider=self.name,
            message="登录失败。最后一次返回：{}".format(errors[-1] if errors else "无响应"),
            raw="\n".join(errors[-3:]),
        )

    # ------------------------------------------------------------ 内部
    def _account_with_suffix(self, username: str) -> str:
        """运营商翻译成账号后缀；账号里已经有 ``@`` 就尊重原样。"""
        username = (username or "").strip()
        if "@" in username:
            return username
        raw = str(self.opt("carrier", "") or "").strip()
        if not raw:
            return username
        code = carrier_mod.normalize(raw)
        suffix = carrier_mod.suffix_for(code)
        if self.opt("isp_suffix") is not None:  # 显式指定优先
            suffix = str(self.opt("isp_suffix"))
        return username + (suffix or "")

    def _as_result(self, resp, endpoint: str) -> LoginResult:
        text = resp.text or ""
        payload = resp.jsonp_payload or text.strip()
        data: Optional[dict] = None
        try:
            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                data = parsed
        except ValueError:
            data = None

        if data is None:
            return LoginResult(False, self.name,
                               "HTTP {} 未识别响应".format(resp.status),
                               endpoint=endpoint, raw=text[:600])

        result = str(data.get("result", "")).strip().lower()
        message = str(data.get("msg") or data.get("message") or "")
        low_msg = message.lower()

        if result in ("1", "success", "true", "ok"):
            return LoginResult(True, self.name, message or "认证成功",
                               endpoint=endpoint, raw=text[:600])
        if any(hint in low_msg or hint in message for hint in _ALREADY_HINTS):
            return LoginResult(True, self.name, message or "已在线",
                               endpoint=endpoint, raw=text[:600], already_online=True)
        return LoginResult(False, self.name, message or "result={}".format(result or "?"),
                           endpoint=endpoint, raw=text[:600])
