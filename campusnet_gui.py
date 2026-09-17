"""GUI 启动入口（PyInstaller 打包用）。

双击运行 = 打开图形界面；
带命令行参数时透传给命令行版（排障用，如：校园网助手.exe doctor）。
"""
import os
import sys

# 无窗口（--windowed）打包的进程里 sys.stdout / sys.stderr 是 **None**。
# 平时的输出都走 cli.Console 的 _safe_write（会跳过 None），但 argparse
# 解析失败时是自己直接往 stderr 写的 —— 不兜住就会以
# "'NoneType' object has no attribute 'write'" 的形式弹崩溃对话框。
# 开机自启场景每次重启都弹，观感极差。
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

from campusnet.gui import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(run())
