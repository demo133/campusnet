"""子进程启动参数：Windows 下不带控制台窗口。

自启的 ``watch`` 用 ``pythonw`` 跑、图形版是无窗口 exe，本身都不显示控制台；
但它们派生的 ``netsh`` / ``ipconfig`` 是控制台程序，每次调用都会闪一个
黑色窗口 —— 开机后头几轮探测集中执行，就成了「终端连续跳很多下」。

``CREATE_NO_WINDOW`` 只在 Windows 存在，且 POSIX 的 ``subprocess``
哪怕传 ``0`` 也会直接 ``ValueError``，所以按平台返回不同的 kwargs，
调用方一律 ``**`` 展开即可，别的地方不用再做平台判断。
"""

import os
import subprocess


def no_window_kwargs() -> dict:
    """Windows 返回隐藏控制台的 creationflags；其它平台返回空 dict。"""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
