"""GUI 启动入口（PyInstaller 打包用）。

双击运行 = 打开图形界面；
带命令行参数时透传给命令行版（排障用，如：校园网助手.exe doctor）。
"""
import sys

from campusnet.gui import run

if __name__ == "__main__":
    sys.exit(run())
