"""新版 eportal（``portal/login`` JSONP）provider。"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from conftest import FakeSession, make_response

from campusnet.providers import EportalPortalProvider, fingerprint, rank
from campusnet.providers.base import DetectContext

OK = 'dr1003({"result":1,"msg":"认证成功","valid":1})'
FAIL = 'dr1003({"result":0,"msg":"账号或密码错误","valid":0})'
ALREADY = 'dr1003({"result":0,"msg":"您已在线，请勿重复登录"})'
PLAIN = '{"result":1,"msg":"认证成功"}'

# 模拟网关重定向出来的门户地址（参数就是最强的指纹）
REDIRECT_URL = ("http://172.19.0.1:801/eportal/portal/login?callback=dr1003"
                "&login_method=1&wlan_user_ip=172.19.10.20&wlan_user_mac="
                "&wlan_ac_name=&jsVersion=4.2.1&lang=zh-cn")


def _ctx() -> DetectContext:
    return DetectContext(url=REDIRECT_URL, text=REDIRECT_URL)


# ---------------------------------------------------------------- 指纹
def test_detect_scores_new_portal_above_classic_eportal():
    scores = dict(fingerprint(_ctx()))

    assert scores.get("eportal_portal", 0) >= 0.6
    assert rank(_ctx())[0] == "eportal_portal"


def test_classic_eportal_page_does_not_trigger_new_provider():
    ctx = DetectContext(url="http://10.0.0.1/eportal/",
                        text="<html>ACSetting DDDDD upass wlanuserip</html>")
    scores = dict(fingerprint(ctx))

    assert scores.get("eportal_portal", 0) < 0.4


# ---------------------------------------------------------------- 登录
def test_login_success_via_jsonp():
    session = FakeSession([("/eportal/portal/login", make_response(OK))])
    provider = EportalPortalProvider(session, {})
    result = provider.login("http://172.19.0.1:801/", "2025123456", "pw",
                            "172.19.10.20", "aabbccddeeff")

    assert result.ok is True
    assert "认证成功" in result.message


def test_login_accepts_plain_json_without_callback():
    session = FakeSession([("/eportal/portal/login", make_response(PLAIN))])
    provider = EportalPortalProvider(session, {})
    result = provider.login("http://172.19.0.1/", "u", "p", "10.0.0.5", "")

    assert result.ok is True


def test_query_carries_full_parameter_set():
    session = FakeSession([("/eportal/portal/login", make_response(OK))])
    provider = EportalPortalProvider(session, {})
    provider.login("http://172.19.0.1/", "2025123456", "p@ss", "172.19.10.20", "x")

    method, url, _ = session.last("GET")
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)

    assert method == "GET"
    assert urlsplit(url).path == "/eportal/portal/login"
    assert query["callback"] == ["dr1003"]
    assert query["login_method"] == ["1"]
    assert query["user_account"] == ["2025123456"]
    assert query["user_password"] == ["p@ss"]
    assert query["wlan_user_ip"] == ["172.19.10.20"]
    assert query["wlan_user_mac"] == ["000000000000"]
    assert query["jsVersion"] == ["4.2.1"]


def test_carrier_becomes_account_suffix():
    session = FakeSession([("/eportal/portal/login", make_response(OK))])
    provider = EportalPortalProvider(session, {"carrier": "cmcc"})
    provider.login("http://172.19.0.1/", "2025123456", "p", "10.0.0.5", "")

    _, url, _ = session.last("GET")
    assert parse_qs(urlsplit(url).query)["user_account"] == ["2025123456@cmcc"]

    session = FakeSession([("/eportal/portal/login", make_response(OK))])
    provider = EportalPortalProvider(session, {"carrier": "unicom"})
    provider.login("http://172.19.0.1/", "2025123456", "p", "10.0.0.5", "")
    _, url, _ = session.last("GET")
    assert parse_qs(urlsplit(url).query)["user_account"] == ["2025123456@unicom"]


def test_campus_carrier_has_no_suffix():
    session = FakeSession([("/eportal/portal/login", make_response(OK))])
    provider = EportalPortalProvider(session, {"carrier": "campus"})
    provider.login("http://172.19.0.1/", "2025123456", "p", "10.0.0.5", "")

    _, url, _ = session.last("GET")
    assert parse_qs(urlsplit(url).query)["user_account"] == ["2025123456"]


def test_username_with_at_is_left_alone():
    session = FakeSession([("/eportal/portal/login", make_response(OK))])
    provider = EportalPortalProvider(session, {"carrier": "cmcc"})
    provider.login("http://172.19.0.1/", "2025123456@telecom", "p", "10.0.0.5", "")

    _, url, _ = session.last("GET")
    assert parse_qs(urlsplit(url).query)["user_account"] == ["2025123456@telecom"]


def test_failure_message_carries_server_text():
    session = FakeSession([("/eportal/portal/login", make_response(FAIL))],
                          default=make_response(FAIL))
    provider = EportalPortalProvider(session, {})
    result = provider.login("http://172.19.0.1/", "u", "bad", "10.0.0.5", "")

    assert result.ok is False
    assert "账号或密码错误" in result.message


def test_already_online_is_detected():
    session = FakeSession([("/eportal/portal/login", make_response(ALREADY))],
                          default=make_response(ALREADY))
    provider = EportalPortalProvider(session, {})
    result = provider.login("http://172.19.0.1/", "u", "p", "10.0.0.5", "")

    assert result.ok is True
    assert result.already_online is True


def test_tries_801_and_803_ports():
    session = FakeSession([("/eportal/portal/login", make_response(FAIL))],
                          default=make_response("", status=404))
    provider = EportalPortalProvider(session, {})
    provider.login("http://172.19.0.1/", "u", "p", "10.0.0.5", "")

    ports = {urlsplit(url).port for url in session.urls}
    assert 801 in ports
    assert 803 in ports
