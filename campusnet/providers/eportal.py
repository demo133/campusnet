"""通用 eportal / ACSetting 认证（华为 Agile Controller 及众多国产 AC 的默认门户）。

这是国内高校最常见的一类"裸 eportal"接口：

``POST /eportal/?c=ACSetting&a=Login``

表单字段沿用早年 Dr.COM 的习惯命名：
``DDDDD``（账号）/ ``upass``（密码）/ ``R1`` / ``R2`` / ``R3`` / ``R6`` / ``para`` / ``0MKKey``。

失败时返回一段 JS：``Msg=01;msga='无法获取用户认证账号！'``；
成功时通常会跳到带 ``Dr.COMWebLoginID_3.htm`` 或 ``success`` 字样的页面。

> Dr.COM 那套服务器也兼容这个接口，所以 ``drcom`` provider 内部也会试它。
> 单独把它列出来，是为了支持那些只有 eportal、没有 ``/drcom/`` 的学校。
"""

from __future__ import annotations

import re
from typing import List

from ..session import local_ip, local_mac
from .base import DetectContext, LoginResult, Provider

FAIL_PATTERN = re.compile(r"Msg\s*=\s*(\d+)\s*;\s*(?:time=\d+\s*;\s*)?msga\s*=\s*'([^']*)'", re.I)


class EportalProvider(Provider):
    name = "eportal"
    display_name = "通用 eportal / 华为 AC"
    min_confidence = 0.4

    @classmethod
    def detect(cls, ctx: DetectContext) -> float:
        score = 0.0
        low = ctx.lower_text
        url = (ctx.url or "").lower()

        if "acsetting" in low or "acsetting" in url:
            score += 0.6
        if "eportal" in url or "eportal" in low:
            score += 0.3
        if ctx.has("ddddd") and ctx.has("upass"):
            score += 0.3
        if "wlanuserip" in low or "wlanacname" in low:
            score += 0.25
        if "华为" in ctx.text or "huawei" in low:
            score += 0.4
        # Dr.COM 的指纹更具体，让 drcom provider 优先
        if "drcom" in low or "dr.comwebloginid" in low:
            score -= 0.35
        return max(0.0, min(score, 1.0))

    def login(self, portal: str, username: str, password: str, client_ip: str = "", mac: str = "") -> LoginResult:
        ip = client_ip or local_ip()
        mac = mac or local_mac()
        errors: List[str] = []

        for origin in self.origins(portal, extra_ports=(801, 803)):
            query = (
                "c=ACSetting&a=Login&protocol=http:&hostname={host}&iTermType=1"
                "&wlanuserip={ip}&wlanacip={ac}&wlanacname=&mac={mac}&ip={ip}"
                "&enAdvert=0&queryACIP=0&loginMethod=1"
            ).format(host=self.ip_from_portal(origin), ip=ip, ac=self.ip_from_portal(origin), mac=mac)
            payload = {
                "DDDDD": username,
                "upass": password,
                "R1": str(self.opt("r1", "0")),
                "R2": "",
                "R3": str(self.opt("r3", "0")),
                "R6": "0",
                "para": str(self.opt("para", "00")),
                "0MKKey": str(self.opt("0MKKey", "123456")),
                "buttonClicked": "",
                "redirect_url": "",
                "err_flag": "",
            }
            url = "{}/eportal/?{}".format(origin, query)
            try:
                resp = self.session.post(url, data=payload, headers={"Referer": origin + "/"})
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
    def _as_result(self, resp, endpoint: str) -> LoginResult:
        text = resp.text or ""

        match = FAIL_PATTERN.search(text)
        if match:
            code, message = match.group(1), match.group(2).strip()
            if code in ("00", "0"):
                return LoginResult(True, self.name, message or "认证成功", endpoint=endpoint, raw=text[:600])
            return LoginResult(False, self.name, "[{}] {}".format(code, message or "认证失败"),
                               endpoint=endpoint, raw=text[:600])

        low = text.lower()
        if "dr.comwebloginid_3.htm" in low or "success" in low or "认证成功" in text:
            return LoginResult(True, self.name, "认证成功", endpoint=endpoint, raw=text[:600])
        if "无法获取用户认证账号" in text:
            return LoginResult(False, self.name, "接口未收到账号参数（该门户可能需要其它字段）",
                               endpoint=endpoint, raw=text[:600])

        return LoginResult(False, self.name, "HTTP {} 未识别响应".format(resp.status),
                           endpoint=endpoint, raw=text[:600])
