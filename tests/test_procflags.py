"""开机自启不闪黑窗：子进程必须带平台正确的 creationflags。

背景：watch 用 ``pythonw`` 跑、图形版是无窗口 exe，但它们派生的
``netsh`` / ``ipconfig`` 是控制台程序，不带 ``CREATE_NO_WINDOW`` 就会
每次调用闪一个黑窗口。这个测试锁住 :mod:`campusnet.procflags` 的
平台行为，防止有人改回硬编码传参。
"""

import os
import subprocess

from campusnet.procflags import no_window_kwargs


def test_flags_match_platform():
    flags = no_window_kwargs()
    if os.name == "nt":
        assert flags == {"creationflags": subprocess.CREATE_NO_WINDOW}
    else:
        # POSIX 的 subprocess 传 creationflags 哪怕是 0 也会 ValueError，
        # 必须什么都不传
        assert flags == {}


def test_flags_are_accepted_by_subprocess_run():
    """返回的 kwargs 要能原样喂给 subprocess.run 不炸（各平台都验）。"""
    completed = subprocess.run(
        ["python", "-c", "print(1)"],
        capture_output=True,
        text=True,
        **no_window_kwargs(),
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == "1"
