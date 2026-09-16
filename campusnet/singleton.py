"""watch 单实例锁：同一台机器同一时刻只允许一个守护进程。

为什么需要
----------

自启入口（Run 键）虽然只有一个，但 GUI 的「保存并立即连接」等路径也可能
拉起一个 watch。两个守护进程同时跑，探测动作翻倍不说，还会互相把对方
刚连好的 Wi-Fi 切走 —— 实测出现过两个 watcher 并存，开机黑窗跳得更多。

用一把**随进程死亡自动释放**的跨进程锁兜底：

- Windows：命名互斥体（内核对象，进程退出即销毁）；
- POSIX：锁文件 + ``flock``（进程死亡内核自动解锁，不会留尸体文件）。

抢不到锁的实例安静退出，不算错误。
"""

import os

_HANDLE = None  # 持锁引用，防 GC / 防重复


def acquire(name: str = "campusnet-watch") -> bool:
    """尝试成为唯一的 watch 实例；抢到返回 True，已被持有返回 False。"""
    global _HANDLE
    if _HANDLE is not None:
        return True  # 本进程已持有
    if os.name == "nt":
        import ctypes

        # use_last_error=True 是必须的：ctypes 自己的内部调用会把
        # GetLastError 冲掉，只有它保存的线程级错误码才可靠
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.CreateMutexW(None, False, "Local\\" + name)
        ERROR_ALREADY_EXISTS = 183
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            return False
        _HANDLE = handle
        return True
    import fcntl

    lock_path = os.path.join(
        os.environ.get("TMPDIR", "/tmp"), "." + name + ".lock"
    )
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    os.write(fd, str(os.getpid()).encode())
    _HANDLE = fd  # 故意不 close：进程活着，锁就在
    return True


def release() -> None:
    """显式释放锁（一般用不到 —— 进程退出时内核自动清理）。"""
    global _HANDLE
    if _HANDLE is None:
        return
    if os.name == "nt":
        # 不 CloseHandle 的话，命名互斥体因为本进程还握着句柄而继续存在，
        # 别的进程会一直看到 ERROR_ALREADY_EXISTS
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if isinstance(_HANDLE, int) and _HANDLE:
            kernel32.CloseHandle(_HANDLE)
    elif isinstance(_HANDLE, int):
        os.close(_HANDLE)
    _HANDLE = None
