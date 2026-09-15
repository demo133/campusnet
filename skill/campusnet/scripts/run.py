#!/usr/bin/env python3
"""定位一个可用的 campusnet 并调用它。

**为什么需要这个包装**：skill 被调用时，用户的机器可能是三种状态之一 ——
装了包、只有一个源码目录、或者什么都没有。直接让调用方去拼
``PYTHONPATH``、判断 ``python`` 还是 ``python3``，很容易出错且每次都要重猜。
这个脚本把这件事收敛成一处。

用法::

    python run.py --version
    python run.py detect --verbose
    python run.py autostart install --interval 5

找不到 campusnet 时，会打印安装命令并以退出码 2 结束。
"""

import importlib.util
import os
import sys

#: 源码目录相对本脚本的位置（``<repo>/skill/campusnet/scripts/run.py``）
_HERE = os.path.dirname(os.path.abspath(__file__))
_SKILL_DIR = os.path.dirname(_HERE)


def _repo_root_candidates():
    """可能的仓库根目录，按可信度排序。

    ``skill/campusnet/scripts/`` 往上三级是仓库根；再往上两级是
    "用户把 skill/ 目录单独拷走了"的情况，也顺带试一下。
    """
    seen = []
    for base in (_SKILL_DIR, os.path.dirname(_SKILL_DIR)):
        for up in (1, 2):
            root = base
            for _ in range(up):
                root = os.path.dirname(root)
            if root and root not in seen:
                seen.append(root)
    return seen


def _ensure_importable():
    """让 ``import campusnet`` 可用，返回来源说明（或 None）。"""
    # 1. 已经装了（pip install / site-packages）
    if importlib.util.find_spec("campusnet") is not None:
        return "已安装"

    # 2. 本机有源码目录 —— 插到 sys.path 最前面
    for root in _repo_root_candidates():
        if os.path.isfile(os.path.join(root, "campusnet", "__init__.py")):
            sys.path.insert(0, root)
            return "本机源码 {}".format(root)

    return None


def _die_not_found():
    sys.stderr.write(
        "未找到 campusnet。任选一种装上后重试：\n"
        "  pip install git+https://github.com/demo133/campusnet.git\n"
        "  git clone https://github.com/demo133/campusnet.git && cd campusnet\n"
    )
    return 2


def main(argv):
    source = _ensure_importable()
    if source is None:
        return _die_not_found()

    try:
        from campusnet.cli import main as cli_main
    except ImportError as exc:  # 装了个坏的 / 源码目录不完整
        sys.stderr.write("导入 campusnet 失败：{}\n".format(exc))
        return _die_not_found()

    # 来源写 stderr：stdout 保持"就是 campusnet 自己的输出"，方便管道和重定向
    sys.stderr.write("[campusnet] {}\n".format(source))
    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
