"""watch 单实例锁：第二个进程必须抢不到。

用独立锁名（``campusnet-test-lock``），避免和真机上前台的
``campusnet-watch`` 守护互相干扰。
"""

import subprocess
import sys
import tempfile

from campusnet import singleton

NAME = "campusnet-test-lock"

CODE = (
    "import sys; from campusnet import singleton; "
    "print('acquired' if singleton.acquire(sys.argv[1]) else 'blocked')"
)


def _attempt() -> str:
    """在**另一个进程**里尝试抢锁（子进程用干净 cwd，防止仓库目录遮蔽包）。"""
    r = subprocess.run(
        [sys.executable, "-c", CODE, NAME],
        capture_output=True, text=True, timeout=30,
        cwd=tempfile.gettempdir(),
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_lock_is_exclusive_across_processes():
    assert singleton.acquire(NAME) is True
    try:
        # 本进程已持有：同进程重复抢也直接成功
        assert singleton.acquire(NAME) is True
        # 另一个进程必须被拦下
        assert _attempt() == "blocked"
    finally:
        singleton.release()
    # 释放后别的进程就能抢到了
    assert _attempt() == "acquired"
