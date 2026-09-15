"""通用 eportal / ACSetting provider。"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from conftest import FakeSession, make_response

from campusnet.providers import EportalProvider

OK = "<html><script>Msg=00;time=0;msga='';</script><body>Success</body></html>"
BAD = "<html><script>Msg=01;time=0;msga='账号或密码错误！';</script><body>Login fail.</body></html>"


def test_success_message():
    session = FakeSession([("/eportal/", make_response(OK))])
    provider = EportalProvider(session, {})

    result = provider.login("http://10.0.0.1/", "2024123456", "pwd", "10.0.0.5", "aabbccddeeff")

    assert result.ok is True


def test_failure_message_carries_server_text():
    session = FakeSession([("/eportal/", make_response(BAD))], default=make_response(BAD))
    provider = EportalProvider(session, {})
    result = provider.login("http://10.0.0.1/", "u", "bad", "10.0.0.5", "")

    assert result.ok is False
    assert "账号或密码错误" in result.message


def test_post_body_contains_account_fields():
    session = FakeSession([("/eportal/", make_response(OK))])
    provider = EportalProvider(session, {})
    provider.login("http://10.0.0.1/", "2024123456", "p@ss", "10.0.0.5", "aabbccddeeff")

    method, url, body = session.last("POST")
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)

    assert method == "POST"
    assert query["c"] == ["ACSetting"] and query["a"] == ["Login"]
    assert isinstance(body, dict)
    assert body["DDDDD"] == "2024123456"
    assert body["upass"] == "p@ss"
    assert body["0MKKey"] == "123456"


def test_tries_801_and_803_ports():
    """经典 eportal 可能挂在 801 或 803，两个都要试。"""
    session = FakeSession([("/eportal/", make_response(BAD))], default=make_response("", status=404))
    provider = EportalProvider(session, {})
    provider.login("http://10.0.0.1/", "u", "p", "10.0.0.5", "")

    ports = {urlsplit(url).port for url in session.urls}
    assert 801 in ports
    assert 803 in ports
