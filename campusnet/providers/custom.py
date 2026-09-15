"""自定义模板 Provider —— 给「学校还没被支持」的人用的逃生舱。

在配置里描述清楚请求长什么样即可，不需要改代码：

```json
{
  "provider": "custom",
  "options": {
    "url": "http://10.0.0.1/eportal/?c=ACSetting&a=Login",
    "method": "POST",
    "body": "DDDDD={username}&upass={password}&wlanuserip={ip}&mac={mac}",
    "headers": {"Referer": "http://10.0.0.1/"},
    "success_regex": "\"result\"\\s*:\\s*1|success",
    "failure_regex": "msga='([^']+)'"
  }
}
```

可用占位符：

| 占位符 | 含义 |
| --- | --- |
| ``{username}`` ``{password}`` | 账号 / 密码（自动 URL 编码） |
| ``{username_raw}`` ``{password_raw}`` | 同上但不编码（放到 JSON body 里时用） |
| ``{ip}`` ``{mac}`` ``{portal}`` ``{ac_id}`` ``{timestamp}`` | 本机 IP、MAC、门户地址、ac_id、当前时间戳 |

自测方式：``campusnet login --provider custom --verbose``，能看到完整请求和响应。
"""

from __future__ import annotations

import re
import time
from typing import Dict
from urllib.parse import quote

from ..session import local_ip, local_mac
from .base import DetectContext, LoginResult, Provider


class CustomProvider(Provider):
    name = "custom"
    display_name = "自定义模板"
    min_confidence = 1.1  # 永远不参与指纹识别，必须显式指定

    @classmethod
    def detect(cls, ctx: DetectContext) -> float:
        return 0.0

    def login(self, portal: str, username: str, password: str, client_ip: str = "", mac: str = "") -> LoginResult:
        url_template = str(self.opt("url", ""))
        if not url_template:
            return LoginResult(False, self.name,
                               "缺少 options.url —— 请先在配置里写清楚登录接口地址")

        ip = client_ip or local_ip()
        mac = mac or local_mac()
        fields = {
            "username": quote(username, safe=""),
            "password": quote(password, safe=""),
            "username_raw": username,
            "password_raw": password,
            "ip": ip,
            "mac": mac,
            "portal": portal,
            "ac_id": str(self.opt("ac_id", "1")),
            "timestamp": str(int(time.time())),
        }

        def fill(text: str) -> str:
            try:
                return text.format(**fields)
            except (KeyError, IndexError, ValueError):
                return text

        url = fill(url_template)
        method = str(self.opt("method", "POST")).upper()
        body = fill(str(self.opt("body", ""))) or None
        headers: Dict[str, str] = dict(self.opt("headers", {}) or {})

        try:
            resp = self.session.request(url, method=method, data=body, headers=headers)
        except Exception as exc:  # noqa: BLE001
            return LoginResult(False, self.name, "请求异常：{}".format(exc), endpoint=url)

        text = resp.text or ""
        success_regex = self.opt("success_regex", "")
        failure_regex = self.opt("failure_regex", "")

        if failure_regex:
            match = re.search(str(failure_regex), text, re.I | re.S)
            if match and not (success_regex and re.search(str(success_regex), text, re.I | re.S)):
                message = match.group(1) if match.groups() else match.group(0)
                return LoginResult(False, self.name, "认证失败：{}".format(message.strip()),
                                   endpoint=url, raw=text[:600])

        if success_regex and re.search(str(success_regex), text, re.I | re.S):
            return LoginResult(True, self.name, "认证成功（匹配 success_regex）",
                               endpoint=url, raw=text[:600])

        if success_regex:
            return LoginResult(False, self.name,
                               "响应未匹配 success_regex（HTTP {}）".format(resp.status),
                               endpoint=url, raw=text[:600])

        # 没配 success_regex 时：HTTP 2xx 就当作成功，最终由联网校验兜底
        ok = 200 <= resp.status < 300
        return LoginResult(ok, self.name,
                           "HTTP {}（未配置 success_regex，以联网校验为准）".format(resp.status),
                           endpoint=url, raw=text[:600])
