"""Dr.COM provider 的请求构造与响应解析。"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from conftest import FakeSession, make_response

from campusnet.providers import DrComProvider

JSONP_OK = 'dr1003({"result":1,"wopt":0,"msg":"","uid":"2024123456","msga":""})'
JSONP_BAD = 'dr1003({"result":0,"msg":1,"uid":"2024123456","msga":"userid error1"})'


def test_detects_drcom_page(ctx_drcom):
    score = DrComProvider.detect(ctx_drcom)
    assert score >= 0.8


def test_does_not_match_empty_page():
    from campusnet.providers.base import DetectContext

    assert DrComProvider.detect(DetectContext(url="http://x/", text="hello")) == 0.0


def test_login_sends_expected_fields():
    session = FakeSession([("/drcom/login", make_response(JSONP_OK))])
    provider = DrComProvider(session, {"carrier": "校园用户"})

    result = provider.login("http://10.99.0.1/", "2024123456", "p@ss word", "10.0.0.5", "aabbccddeeff")

    assert result.ok is True
    call = session.find("/drcom/login")
    assert call is not None and call[0] == "GET"

    query = parse_qs(urlsplit(call[1]).query, keep_blank_values=True)
    assert query["DDDDD"] == ["2024123456"]
    assert query["upass"] == ["p@ss word"]          # 密码里的空格/符号必须被正确编码
    assert query["0MKKey"] == ["123456"]
    assert query["R1"] == ["0"] and query["R2"] == [""] and query["R3"] == ["0"]
    assert query["para"] == ["00"]
    assert query["callback"] == ["dr1003"]


def test_carrier_changes_params():
    session = FakeSession([("/drcom/login", make_response(JSONP_OK))])
    provider = DrComProvider(session, {"carrier": "校园联通"})
    provider.login("http://10.0.0.1/", "u", "p", "10.0.0.5", "")

    query = parse_qs(urlsplit(session.find("/drcom/login")[1]).query)
    assert query["R3"] == ["1"]


def test_mobile_carrier_appends_suffix():
    session = FakeSession([("/drcom/login", make_response(JSONP_OK))])
    provider = DrComProvider(session, {"carrier": "移动"})
    provider.login("http://10.0.0.1/", "2024123456", "p", "10.0.0.5", "")

    query = parse_qs(urlsplit(session.find("/drcom/login")[1]).query)
    assert query["DDDDD"] == ["2024123456@cmcc"]


def test_bad_password_is_reported():
    session = FakeSession([("/drcom/login", make_response(JSONP_BAD))],
                          default=make_response(JSONP_BAD))
    provider = DrComProvider(session, {})
    result = provider.login("http://10.0.0.1/", "u", "wrong", "10.0.0.5", "")

    assert result.ok is False
    assert "userid error1" in result.message


def test_falls_back_to_eportal_when_jsonp_fails():
    """传统接口失败时，应该自动换到 801 端口的 eportal 接口。"""
    session = FakeSession(
        routes=[
            ("/drcom/login", make_response("Error code: 203 Bad request(2)", status=203)),
            (":801/eportal/", make_response("<html><script>Msg=00;time=0;msga='';</script></html>")),
        ],
        default=make_response("", status=404),
    )
    provider = DrComProvider(session, {})
    result = provider.login("http://10.0.0.1/", "u", "p", "10.0.0.5", "")

    assert any(":801/eportal/" in url for url in session.urls)
    assert result.endpoint.endswith(":801/eportal/")


def test_success_page_marker_is_recognised():
    """有些学校不回 JSON，只回带 Dr.COMWebLoginID_3.htm 的页面。"""
    session = FakeSession([
        ("/drcom/login", make_response("<script><!--Dr.COMWebLoginID_3.htm--></script>")),
    ])
    provider = DrComProvider(session, {})
    result = provider.login("http://10.0.0.1/", "u", "p", "10.0.0.5", "")
    assert result.ok is True
