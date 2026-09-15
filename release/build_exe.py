"""一键打包 Windows exe（绿色便携、双击即用）。

用法（在仓库根目录，用装了 campunet 的那个 Python 跑）：

    python release/build_exe.py

产物：
    dist/校园网助手.exe                      ← 分发这个
    build/smoke/campusnet-console.exe        ← 调试自检用，发布前可删

流程：装构建依赖 → 生成图标 → 先出带控制台的调试版（自检 keyring 等）
→ 再出正式的无窗口版。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable
APP_NAME = "校园网助手"


def sh(cmd) -> None:
    print("+ " + " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode:
        sys.exit("命令失败（exit {}）：{}".format(result.returncode, cmd))


def ensure_deps() -> None:
    try:
        import PyInstaller  # noqa: F401
        import PIL  # noqa: F401
    except ImportError:
        sh([PY, "-m", "pip", "install", "--quiet",
            "pyinstaller>=6.0", "pillow>=10.0"])


def main() -> None:
    ensure_deps()

    # 图标：先有 ico 才能编正式版
    sh([PY, os.path.join("release", "make_icon.py")])

    # 1) 调试版（带控制台）：打包环境自检用 —— 能看见输出、能跑 doctor
    sh([PY, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
        "--console", "--name", "campusnet-console",
        "--distpath", os.path.join("build", "smoke"),
        "--workpath", os.path.join("build", "smoke-work"),
        "--specpath", os.path.join("build", "smoke-spec"),
        "campusnet_gui.py"])

    # 2) 正式版（无黑窗口 + 图标）：keyring 后端要显式带上
    # 注意：icon 必须绝对路径 —— PyInstaller 会相对 --specpath 解析它
    icon = os.path.join(ROOT, "release", "app_icon.ico")
    sh([PY, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
        "--windowed", "--icon", icon,
        "--collect-submodules", "keyring.backends",
        "--name", APP_NAME,
        "--specpath", os.path.join("build", "spec"),
        "campusnet_gui.py"])

    print()
    print("打包完成：")
    print("  正式版  dist/{}.exe".format(APP_NAME))
    print("  调试版  build/smoke/campusnet-console.exe（发布前可删）")


if __name__ == "__main__":
    main()
