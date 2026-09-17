"""打包版（PyInstaller frozen）的自启命令与入口健壮性。

背景：图形版 exe 里点「开机自启」后，下次开机直接弹崩溃框——
自启命令误用了源码模式的 ``-m campusnet`` 参数（argparse invalid choice），
而无窗口进程的 stderr 是 None，argparse 报错写不出去，连环炸。
"""

import sys

from campusnet import autostart, cli


def test_base_command_normal_mode(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    cmd = autostart._base_command("C:/cfg.json", 10)

    assert "-m" in cmd and "campusnet" in cmd and "watch" in cmd
    assert cmd[-2:] == ["--config", "C:/cfg.json"]


def test_base_command_frozen_exe(monkeypatch):
    """打包成 exe 后不能再带 -m：参数由入口透传给 CLI。"""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    cmd = autostart._base_command("C:/cfg.json", 10)

    assert cmd[0] == sys.executable
    assert "-m" not in cmd
    assert cmd[1] == "watch"
    assert "--interval" in cmd and "10" in cmd
    assert cmd[-2:] == ["--config", "C:/cfg.json"]


def test_main_survives_none_streams(monkeypatch):
    """无窗口进程里 stdout/stderr 是 None：argparse 报错也不能崩成 AttributeError。"""
    monkeypatch.setattr(sys, "stdout", None, raising=False)
    monkeypatch.setattr(sys, "stderr", None, raising=False)

    # 非法子命令 → argparse 走 parser.error：写 stderr、SystemExit(2)。
    # 没有兜底的话这里会先炸 'NoneType' has no attribute 'write'。
    try:
        cli.main(["definitely-not-a-command"])
        raised = None
    except SystemExit as exc:
        raised = exc
    except AssertionError:
        raise
    except AttributeError as exc:
        raise AssertionError("None 流没兜住：{}".format(exc))

    assert raised is not None and raised.code == 2
