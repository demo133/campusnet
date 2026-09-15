"""配置读写与凭据解析。"""

from __future__ import annotations

import json
import os
import stat

import pytest

from campusnet.config import Config, default_config_path
from campusnet.session import Response


def test_roundtrip(tmp_path):
    path = str(tmp_path / "config.json")
    cfg = Config(username="2024123456", provider="drcom", portal_ip="http://10.0.0.1/",
                 options={"ac_id": "1", "carrier": "校园用户"})
    cfg.save(path, include_password=False)

    loaded = Config.load(path)
    assert loaded.username == "2024123456"
    assert loaded.provider == "drcom"
    assert loaded.portal_ip == "http://10.0.0.1/"
    assert loaded.options["ac_id"] == "1"


def test_password_not_written_by_default(tmp_path):
    path = str(tmp_path / "config.json")
    cfg = Config(username="u", password="topsecret")
    cfg.save(path)

    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()

    assert "topsecret" not in raw
    assert "password" not in json.loads(raw)


def test_password_written_only_when_asked(tmp_path):
    path = str(tmp_path / "config.json")
    cfg = Config(username="u", password="topsecret")
    cfg.save(path, include_password=True)

    with open(path, "r", encoding="utf-8") as fh:
        assert "topsecret" in fh.read()


def test_env_overrides_file(tmp_path, monkeypatch):
    path = str(tmp_path / "config.json")
    Config(username="from-file", provider="drcom").save(path)

    monkeypatch.setenv("CAMPUSNET_USERNAME", "from-env")
    monkeypatch.setenv("CAMPUSNET_PROVIDER", "srun")
    monkeypatch.setenv("CAMPUSNET_OPTIONS", '{"ac_id": "9"}')

    cfg = Config.load(path)
    assert cfg.username == "from-env"
    assert cfg.provider == "srun"
    assert cfg.options["ac_id"] == "9"


def test_password_from_env(monkeypatch):
    monkeypatch.setenv("CAMPUSNET_PASSWORD", "env-secret")
    cfg = Config(username="u")
    assert cfg.resolve_password() == "env-secret"
    assert cfg.password_source == "env"


def test_missing_credentials_return_empty(monkeypatch):
    monkeypatch.delenv("CAMPUSNET_PASSWORD", raising=False)
    cfg = Config(username="u", password="")
    assert cfg.resolve_password(prompt=False, allow_keyring=False) == ""
    assert cfg.masked() == "未设置"


def test_invalid_json_raises_readable_error(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ this is not json", encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        Config.load(str(path))
    assert "JSON" in str(excinfo.value)


def test_default_path_is_platform_specific():
    path = default_config_path()
    assert path.endswith("config.json")
    assert "campusnet" in path


def test_file_permissions_on_posix(tmp_path):
    if os.name == "nt":
        pytest.skip("Windows 不用 POSIX 权限位")
    path = str(tmp_path / "config.json")
    Config(username="u").save(path)
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_response_decodes_gbk_portal_page():
    """国内门户大量使用 gb2312，解码必须正确。"""
    body = "<title>上网登录页</title>".encode("gb18030")
    resp = Response(200, {"Content-Type": "text/html; charset=gb2312"}, body, "http://x/")
    assert "上网登录页" in resp.text


def test_jsonp_payload_extraction():
    resp = Response(200, {}, b'dr1003({"result":1})', "http://x/")
    assert resp.jsonp_payload == '{"result":1}'
    assert Response(200, {}, b"plain text", "http://x/").jsonp_payload is None
