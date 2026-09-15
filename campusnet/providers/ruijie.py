"""锐捷 Ruijie ePortal 认证（``/eportal/InterFace.do``）。

接口：

``POST /eportal/InterFace.do?method=login``

表单字段：``userId`` / ``password`` / ``service`` / ``queryString`` 等。
其中 ``queryString`` 是门户页面 URL 里带的那一串（形如
``wlanuserip=...&wlanacname=...&nasip=...``），第一次请求时从页面里抠出来。

响应是 JSON：``{"result":"success","message":"..."}``。
"""

from __future__ import annotations

import json
from typing import List, Optional

from ..session import local_ip
from .base import DetectContext, LoginResult, Provider


class RuijieProvider(Provider):
    name = "ruijie"
    display_name = "锐捷 Ruijie"
    docs = "https://www.ruijie.com.cn/"
    min_confidence = 0.4

    @classmethod
    def detect(cls, ctx: DetectContext) -> float:
        score = 0.0
        low = ctx.lower_text
        url = (ctx.url or "").lower()

        if "interface.do" in low or "interface.do" in url:
            score += 0.75
        if "querystring" in low:
            score += 0.3
        if "锐捷" in ctx.text or "ruijie" in low:
            score += 0.6
        if "/eportal/" in url:
            score += 0.2
        if "wlanacname" in low or "wlanuserip" in low:
            score += 0.15
        return min(score, 1.0)

    def login(self, portal: str, username: str, password: str, client_ip: str = "", mac: str = "") -> LoginResult:
        ip = client_ip or local_ip()
        service = str(self.opt("service", ""))
        errors: List[str] = []

        for origin in self.origins(portal):
            query_string = self.opt("query_string", "") or self._fetch_query_string(origin, ip)
            payload = {
                "userId": username,
                "password": password,
                "service": service,
                "queryString": query_string,
                "operatorPwd": "",
                "operatorUserId": "",
                "validcode": "",
                "passwordEncrypt": "false",
            }
            url = "{}/eportal/InterFace.do?method=login".format(origin)
            try:
                resp = self.session.post(url, data=payload, headers={
                    "Referer": "{}/eportal/".format(origin),
                    "Origin": origin,
                })
            except Exception as exc:  # noqa: BLE001
                errors.append("{}：{}".format(origin, exc))
                continue

            result = self._as_result(resp, url)
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
    def _fetch_query_string(self, origin: str, ip: str) -> str:
        """从门户页面里抠出 queryString。"""
        try:
            resp = self.session.get("{}/eportal/?c=ACSetting".format(origin),
                                    headers={"Referer": origin + "/"})
        except Exception:  # noqa: BLE001
            return ""
        text = resp.text
        found = self.find(r'queryString["\']?\s*[:=]\s*["\']([^"\']+)', text)
        if found:
            return found
        # 退化方案：自己拼一份
        return "wlanuserip={ip}&wlanacname=&nasip={origin}".format(ip=ip, origin=self.ip_from_portal(origin))

    def _as_result(self, resp, endpoint: str) -> LoginResult:
        text = resp.text or ""
        data: Optional[dict] = None
        payload = resp.jsonp_payload or text.strip()
        try:
            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                data = parsed
        except ValueError:
            data = None

        if data:
            result = str(data.get("result", "")).lower()
            message = str(data.get("message") or data.get("msg") or "")
            if result in ("success", "ok", "1", "true"):
                return LoginResult(True, self.name, message or "认证成功", endpoint=endpoint, raw=text[:600])
            if "already" in message.lower() or "已在线" in message:
                return LoginResult(True, self.name, message, endpoint=endpoint,
                                   raw=text[:600], already_online=True)
            return LoginResult(False, self.name, message or "result={}".format(result),
                               endpoint=endpoint, raw=text[:600])

        if "success" in text.lower():
            return LoginResult(True, self.name, "认证成功", endpoint=endpoint, raw=text[:600])
        return LoginResult(False, self.name, "HTTP {} 未识别响应".format(resp.status),
                           endpoint=endpoint, raw=text[:600])
