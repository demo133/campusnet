"""深澜 Srun 的加密算法与请求构造。

``srun_base64`` 用的是深澜自己置换过的字母表 —— 这是最容易写错的地方，
所以单独测：编码结果必须只能用那 64 个字符，且能反解回原文。
"""

from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlsplit

from conftest import FakeSession, make_response

from campusnet.providers import SrunProvider
from campusnet.providers.srun import (
    SRUN_ALPHABET,
    build_chksum,
    build_hmd5,
    build_info,
    srun_base64,
    xor_bytes,
)


def _decode_srun(text: str) -> bytes:
    """把深澜 base64 还原：换回标准字母表再补 ``=``。"""
    table = {ord(c): ord(s) for c, s in zip(SRUN_ALPHABET[:64],
                                            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")}
    standard = text.translate(table)
    standard += "=" * (-len(standard) % 4)
    return base64.b64decode(standard)


# -------------------------------------------------------------------- 算法
def test_alphabet_shape():
    assert len(SRUN_ALPHABET) == 65
    assert SRUN_ALPHABET[-1] == "="
    assert len(set(SRUN_ALPHABET[:64])) == 64


def test_base64_is_permuted_not_standard():
    raw = b"hello srun"
    assert srun_base64(raw) != base64.b64encode(raw).decode().rstrip("=")
    assert set(srun_base64(raw)) <= set(SRUN_ALPHABET[:64])


def test_base64_roundtrip():
    for raw in (b"", b"a", b"ab", b"abc", b'{"k":"v"}', "中文".encode("utf-8")):
        assert _decode_srun(srun_base64(raw)) == raw


def test_xor_bytes_wraps_key():
    assert xor_bytes(b"\x00\x00\x00\x00", b"ab") == b"abab"
    assert xor_bytes(b"ab", b"ab") == b"\x00\x00"
    assert xor_bytes(b"data", b"") == b"data"


def test_hmd5_matches_md5_of_password_plus_challenge():
    import hashlib

    challenge = "1a2b3c"
    assert build_hmd5("secret", challenge) == hashlib.md5(("secret" + challenge).encode()).hexdigest()


def test_info_is_srbx1_wrapped_and_reversible():
    challenge = "abc123"
    info = build_info("2024123456", "pwd", "10.0.0.5", "1", challenge)

    assert info.startswith("{SRBX1}")
    payload = _decode_srun(info[len("{SRBX1}"):])
    decoded = json.loads(xor_bytes(payload, challenge.encode()).decode("utf-8"))

    assert decoded == {
        "username": "2024123456",
        "password": "pwd",
        "ip": "10.0.0.5",
        "acid": "1",
        "enc_ver": "srun_bx1",
    }


def test_chksum_is_sha1_hex():
    value = build_chksum("c", "u", "h", "1", "10.0.0.5", "info")
    assert len(value) == 40
    int(value, 16)  # 是合法十六进制

    # 同样的输入必须得到同样的输出
    assert value == build_chksum("c", "u", "h", "1", "10.0.0.5", "info")


# -------------------------------------------------------------------- 请求
def test_detect_srun_page():
    from campusnet.providers.base import DetectContext

    page = '<script src="/cgi-bin/srun_portal"></script><a href="/cgi-bin/get_challenge">x</a>'
    assert SrunProvider.detect(DetectContext(url="http://10.0.0.1/srun_portal_pc", text=page)) >= 0.7


def test_login_flow_and_params():
    session = FakeSession(routes=[
        ("get_challenge", make_response('jsonp({"challenge":"9f8e7d","client_ip":"10.0.0.5","res":"ok"})')),
        ("srun_portal", make_response('jsonp({"error":"ok","error_msg":""})')),
    ])
    provider = SrunProvider(session, {"ac_id": "1"})

    result = provider.login("http://10.0.0.1/", "2024123456", "secret", "10.0.0.5", "")

    assert result.ok is True
    assert session.find("get_challenge") is not None

    call = session.find("srun_portal")
    assert call is not None
    query = parse_qs(urlsplit(call[1]).query)

    assert query["action"] == ["login"]
    assert query["username"] == ["2024123456"]
    assert query["password"][0].startswith("{MD5}")
    assert query["ac_id"] == ["1"]
    assert query["ip"] == ["10.0.0.5"]
    assert query["n"] == ["200"] and query["type"] == ["1"]
    assert query["info"][0].startswith("{SRBX1}")
    assert len(query["chksum"][0]) == 40


def test_error_response_is_reported():
    session = FakeSession(routes=[
        ("get_challenge", make_response('jsonp({"challenge":"abc"})')),
        ("srun_portal", make_response('jsonp({"error":"password_error","error_msg":"密码错误"})')),
    ])
    provider = SrunProvider(session, {})
    result = provider.login("http://10.0.0.1/", "u", "bad", "10.0.0.5", "")

    assert result.ok is False
    assert "password_error" in result.message
