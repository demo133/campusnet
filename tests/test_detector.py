"""指纹识别：给一段页面，必须认出对的认证系统。"""

from __future__ import annotations

import pytest

from campusnet.providers import PROVIDERS, fingerprint
from campusnet.providers.base import DetectContext

SRUN_PAGE = """
<html><head><title>校园网自助服务</title></head>
<body>
<script>var ac_id = "1";</script>
<form action="/cgi-bin/srun_portal" method="get"></form>
</body></html>
"""

RUIJIE_PAGE = """
<html><body>
<script>var queryString = "wlanuserip=10.0.0.5&wlanacname=RG-AC";</script>
<form action="/eportal/InterFace.do?method=login"></form>
</body></html>
"""

HUAWEI_PAGE = """
<html><body>
<form action="/eportal/?c=ACSetting&a=Login" method="post">
  <input name="DDDDD"><input name="upass" type="password">
</form>
<script>var wlanuserip="10.0.0.5";</script>
</body></html>
"""


def _ctx(text: str, url: str = "http://10.0.0.1/", server: str = "") -> DetectContext:
    return DetectContext(url=url, text=text, headers={"server": server} if server else {})


def test_drcom_wins_on_real_page(ctx_drcom):
    names = [name for name, _ in fingerprint(ctx_drcom)]
    assert names, "真实 Dr.COM 页面必须能识别出来"
    assert names[0] == "drcom"


def test_srun_page():
    assert fingerprint(_ctx(SRUN_PAGE))[0][0] == "srun"


def test_ruijie_page():
    assert fingerprint(_ctx(RUIJIE_PAGE))[0][0] == "ruijie"


def test_huawei_eportal_page():
    assert fingerprint(_ctx(HUAWEI_PAGE))[0][0] == "eportal"


def test_unknown_page_returns_nothing():
    assert fingerprint(_ctx("<html><body>hello world</body></html>")) == []


def test_custom_provider_never_auto_selected():
    """custom 必须显式指定，绝不能因为"没认出来"就被自动选中。"""
    assert PROVIDERS["custom"].min_confidence > 1.0
    for sample in (SRUN_PAGE, RUIJIE_PAGE, HUAWEI_PAGE, "<html>whatever</html>"):
        assert "custom" not in [name for name, _ in fingerprint(_ctx(sample))]


@pytest.mark.parametrize("name", list(PROVIDERS))
def test_every_provider_survives_weird_input(name):
    """任何 provider 遇到畸形输入都不该抛异常。"""
    ctx = _ctx("")
    ctx.headers = {}
    score = PROVIDERS[name].detect(ctx)
    assert 0.0 <= score <= 1.0

    garbage = _ctx("\x00\x01\x02 not html at all " * 5)
    assert 0.0 <= PROVIDERS[name].detect(garbage) <= 1.0
