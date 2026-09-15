"""运营商（ISP）归一化与各 provider 的参数翻译测试。

这个模块锁住几件**曾经出过错**的事：

1. :func:`normalize` 必须幂等 —— ``campus_telecom`` 不能被子串匹配降级成 ``telecom``；
2. 长别名优先 —— ``校园宽带(移动)`` 要变成「移动」而不是「校园用户」；
3. ``校园电信`` / ``校园联通`` 在 Dr.COM 上走 ``R1=1`` / ``R3=1``，
   和纯电信/联通的账号后缀不是一回事，不能被合并；
4. Srun 的 ``domain`` 要能正常发出去，且账号自带 ``@xxx`` 时不重复拼。
"""

from __future__ import annotations

import pytest

from campusnet import carrier
from campusnet.providers.drcom import DrComProvider
from campusnet.providers.srun import SrunProvider
from campusnet.session import Response


class FakeSession:
    """记录请求的假 Session —— 不发网络，只把 URL 存下来。

    ``get_challenge`` 是 Srun 登录流程里**先**要过的一步，所以这里对它
    回一个带 ``challenge`` 的 JSONP；其他请求一律抛异常停下，
    我们只关心「认证请求的 URL 长什么样」。
    """

    def __init__(self):
        self.urls = []

    def get(self, url, **kw):
        self.urls.append(url)
        if "get_challenge" in url:
            body = b'jsonp({"challenge":"abc123","client_ip":"10.1.2.3"})'
            return Response(200, {"content-type": "text/plain; charset=utf-8"},
                            body, url)
        raise RuntimeError("停止在这里，我们只关心 URL")

    def post(self, url, **kw):
        self.urls.append(url)
        raise RuntimeError("停止在这里，我们只关心 URL")

    def request(self, url, **kw):
        return self.get(url, **kw)


def _drcom(carrier_value):
    """构造一个只看 carrier 的 DrComProvider。"""
    options = {}
    if carrier_value is not None:
        options["carrier"] = carrier_value
    return DrComProvider(FakeSession(), options)


# --------------------------------------------------------------------------
# normalize：幂等性
# --------------------------------------------------------------------------

ALL_CODES = ["campus", "cmcc", "telecom", "unicom", "other",
             "campus_telecom", "campus_unicom"]


@pytest.mark.parametrize("code", ALL_CODES)
def test_normalize_is_idempotent(code):
    """代号喂回去必须原样吐出。

    这条曾经真实出过 bug：``normalize('campus_telecom')`` 返回 ``'telecom'``，
    把 Dr.COM 的「校园电信」（R1=1）静默降级成纯「电信」（R1=0），
    登录必然失败而且看不出原因。
    """
    once = carrier.normalize(code)
    assert once == code, "第一遍就把 {} 改坏了".format(code)
    assert carrier.normalize(once) == once, "{} 不幂等".format(code)


@pytest.mark.parametrize("code", ALL_CODES)
def test_label_roundtrip_through_normalize(code):
    """``normalize(label(code))`` 还得是 code。

    因为 ``campusnet carrier`` 之类的命令会把显示名再喂回 normalize。
    """
    shown = carrier.label(code)
    assert carrier.normalize(shown) == code


def test_normalize_empty_and_whitespace():
    assert carrier.normalize("") == ""
    assert carrier.normalize("   ") == ""
    assert carrier.normalize(None) == ""


# --------------------------------------------------------------------------
# normalize：别名匹配
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    # 校园用户
    ("校园用户", "campus"),
    ("校园网", "campus"),
    ("校园", "campus"),
    ("默认", "campus"),
    ("campus", "campus"),
    # 移动
    ("移动", "cmcc"),
    ("中国移动", "cmcc"),
    ("中国移动(CMCC)", "cmcc"),
    ("CMCC", "cmcc"),
    ("China Mobile", "cmcc"),
    # 电信
    ("电信", "telecom"),
    ("中国电信", "telecom"),
    ("China Telecom", "telecom"),
    ("CT", "telecom"),
    # 联通
    ("联通", "unicom"),
    ("中国联通", "unicom"),
    ("Unicom", "unicom"),
    # 其他
    ("其他", "other"),
    ("其它", "other"),
    ("other", "other"),
    # 带括号注释 / 子串
    ("校园宽带(移动)", "cmcc"),
    ("中国移动校园宽带", "cmcc"),
    ("中国电信(CT)", "telecom"),
])
def test_normalize_aliases(text, expected):
    assert carrier.normalize(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("校园电信", "campus_telecom"),
    ("校内电信", "campus_telecom"),
    ("校园联通", "campus_unicom"),
    ("校内联通", "campus_unicom"),
])
def test_campus_isp_keeps_its_own_code(text, expected):
    """「校园电信」/「校园联通」必须是独立代号。

    它们在 Dr.COM 页面上是独立的「服务类型」，走 R1=1 / R3=1；
    如果被归并成纯 telecom/unicom（只加账号后缀），参数就发错了。
    """
    assert carrier.normalize(text) == expected


def test_long_alias_wins_over_short_one():
    """``校园宽带(移动)`` 里既有 ``校园`` 也有 ``移动``。

    短别名 ``校园`` 若先生效，用户说「移动」却被当成「校园用户」。
    按长度从长到短匹配 + 括号内容优先，可以避免。
    这也是这条测试存在的理由。
    """
    assert carrier.normalize("校园宽带(移动)") == "cmcc"


def test_unknown_value_passes_through_unchanged():
    """认不出的运营商不报错，原样返回。

    很多学校的运营商就体现在账号后缀上，原样透传恰好是对的。
    """
    assert carrier.normalize("神秘运营商") == "神秘运营商"
    assert carrier.normalize("some-isp") == "some-isp"
    assert not carrier.is_known("神秘运营商")


def test_is_known():
    for code in ALL_CODES:
        assert carrier.is_known(code)
    assert not carrier.is_known("")
    assert not carrier.is_known("电信")  # 这是别名不是代号


# --------------------------------------------------------------------------
# suffix_for
# --------------------------------------------------------------------------

@pytest.mark.parametrize("code,expected", [
    ("campus", ""),
    ("other", ""),
    ("cmcc", "@cmcc"),
    ("telecom", "@telecom"),
    ("unicom", "@unicom"),
    # 校园电信/联通靠 R1/R3 区分，不加后缀
    ("campus_telecom", ""),
    ("campus_unicom", ""),
])
def test_suffix_for_known(code, expected):
    assert carrier.suffix_for(code) == expected


def test_suffix_for_unknown_gets_at_prefix():
    assert carrier.suffix_for("神秘运营商") == "@神秘运营商"
    assert carrier.suffix_for("@custom") == "@custom", "已经是 @ 开头就别再加"


def test_suffix_for_empty_uses_default():
    assert carrier.suffix_for("") == ""
    assert carrier.suffix_for("", default="@x") == "@x"


# --------------------------------------------------------------------------
# label / 选项表
# --------------------------------------------------------------------------

def test_label_known_and_unknown():
    assert carrier.label("cmcc") == "中国移动"
    assert carrier.label("") == "未指定"
    assert carrier.label("神秘运营商") == "神秘运营商"


def test_choices_cover_all_codes():
    codes = {code for code, _ in carrier.CHOICES}
    codes |= {code for code, _ in carrier.EXTRA_CHOICES}
    assert codes == set(ALL_CODES)


def test_every_code_has_label_and_suffix():
    for code in ALL_CODES:
        assert code in carrier.LABELS
        assert code in carrier.DEFAULT_SUFFIX


# --------------------------------------------------------------------------
# Dr.COM 翻译
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value,r1,r3,para,suffix", [
    ("", "0", "0", "00", ""),          # 不设置 = 校园用户
    ("campus", "0", "0", "00", ""),
    ("移动", "0", "0", "30", "@cmcc"),
    ("电信", "0", "0", "00", "@telecom"),
    ("联通", "0", "0", "00", "@unicom"),
    ("校园电信", "1", "0", "00", ""),  # R1=1
    ("校园联通", "0", "1", "00", ""),  # R3=1
    ("校园其他", "0", "0", "30", ""),
])
def test_drcom_resolve_carrier(value, r1, r3, para, suffix):
    assert _drcom(value).resolve_carrier() == (r1, r3, para, suffix)


def test_drcom_campus_telecom_is_not_plain_telecom():
    """这条是防回归的重点：两个档位的 R1 不同，绝不能混。"""
    campus = _drcom("校园电信").resolve_carrier()
    plain = _drcom("电信").resolve_carrier()
    assert campus != plain
    assert campus[0] == "1" and plain[0] == "0"


def test_drcom_campus_unicom_is_not_plain_unicom():
    campus = _drcom("校园联通").resolve_carrier()
    plain = _drcom("联通").resolve_carrier()
    assert campus != plain
    assert campus[1] == "1" and plain[1] == "0"


def test_drcom_unknown_carrier_becomes_suffix():
    """认不出的运营商：退化成「校园其他」的 R1/R3 + 账号后缀。"""
    r1, r3, para, suffix = _drcom("神秘运营商").resolve_carrier()
    assert (r1, r3) == ("0", "0")
    assert suffix == "@神秘运营商"


def test_drcom_explicit_options_override_carrier():
    """显式写了 r1/r3/para/username_suffix 的，以显式为准。"""
    provider = DrComProvider(
        FakeSession(),
        {"carrier": "移动", "r1": "9", "r3": "8",
         "para": "77", "username_suffix": "@mine"},
    )
    assert provider.resolve_carrier() == ("9", "8", "77", "@mine")


def test_drcom_login_appends_suffix_to_username():
    """后缀要真的拼进用户名里发给服务端。"""
    session = FakeSession()
    provider = DrComProvider(session, {"carrier": "移动"})
    try:
        provider.login("http://10.0.0.1", "2200000000", "pw")
    except Exception:
        pass
    joined = " ".join(session.urls)
    assert "2200000000%40cmcc" in joined or "2200000000@cmcc" in joined, joined


# --------------------------------------------------------------------------
# Srun 翻译
# --------------------------------------------------------------------------

def _srun_urls(carrier_value=None, domain=None, username="2200000000"):
    """跑一遍 Srun 登录，返回它实际请求过的 URL 列表。"""
    options = {}
    if carrier_value:
        options["carrier"] = carrier_value
    if domain:
        options["domain"] = domain
    session = FakeSession()
    provider = SrunProvider(session, options)
    try:
        provider.login("http://10.0.0.1", username, "pw", client_ip="10.1.2.3")
    except Exception:
        pass
    return " ".join(session.urls)


def test_srun_carrier_becomes_domain():
    url = _srun_urls(carrier_value="移动")
    assert "domain=cmcc" in url


def test_srun_explicit_domain_wins():
    url = _srun_urls(domain="telecom")
    assert "domain=telecom" in url


def test_srun_domain_strips_at_sign():
    url = _srun_urls(domain="@cmcc")
    assert "domain=cmcc" in url
    assert "%40cmcc" not in url and "@cmcc" not in url


def test_srun_no_domain_when_username_has_at():
    """账号自带 ``@cmcc`` 时就别再拼 domain 了，否则会变成 ``xx@cmcc@cmcc``。"""
    url = _srun_urls(carrier_value="移动", username="2200000000@cmcc")
    assert "domain=" not in url


def test_srun_no_carrier_no_domain():
    url = _srun_urls()
    assert "domain=" not in url


def test_srun_campus_carrier_has_empty_suffix():
    """校园用户没有后缀，不该凭空冒出 ``domain=``。"""
    url = _srun_urls(carrier_value="campus")
    assert "domain=" not in url
