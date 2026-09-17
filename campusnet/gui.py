"""campusnet 图形界面（给完全不懂命令行的人用）。

设计原则：

- 双击就能用：第一次运行自动引导填账号，之后一键连接；
- **所有**报错都翻译成大白话，技术细节落到本地日志文件里；
- 只依赖标准库（tkinter）。``keyring`` 可选 —— 打包版自带，
  用来把密码存进系统凭据管理器，磁盘上不留明文。

打包方式见 ``release/build_exe.py``。
"""

from __future__ import annotations

import base64
import datetime
import os
import queue
import sys
import threading
import traceback
from typing import Any, Dict, List, Optional, Tuple

from . import __version__, autostart, carrier
from . import wifi as _wifi
from .config import Config, _keyring_set, has_keyring
from .runner import Runner

APP_TITLE = "校园网助手"
#: 冒烟自检用的环境变量：值为"秒数"（如 "2"），加 ",setup" 表示同时打开设置页
SMOKE_ENV = "CAMPUSNET_GUI_SMOKE"
ERROR_LOG_NAME = "gui-errors.log"

# ---------------------------------------------------------------- 主题色
BG = "#f4f6fa"
CARD = "#ffffff"
TEXT = "#1f2937"
MUTED = "#6b7280"
GREEN = "#15803d"
RED = "#b91c1c"
BLUE = "#2563eb"
BLUE_DARK = "#1d4ed8"
GRAY_BTN = "#e5e7eb"

FONT = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 16, "bold")


# ---------------------------------------------------------------- 错误与日志
def _error_log_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "campusnet", ERROR_LOG_NAME)


def _write_error_log(detail: str) -> str:
    """把技术细节追加到本地日志，返回路径（失败返回空串）。"""
    try:
        path = _error_log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n---- {} ----\n{}\n".format(
                datetime.datetime.now().isoformat(timespec="seconds"), detail))
        return path
    except Exception:  # noqa: BLE001 - 日志写不进去也不能二次报错
        return ""


def friendly_message(exc: BaseException) -> str:
    """把异常翻译成人话。"""
    import socket
    import urllib.error

    if isinstance(exc, (urllib.error.URLError, socket.timeout,
                        ConnectionError, TimeoutError, OSError)):
        return ("连不上校园网认证服务。\n\n"
                "请先确认电脑已经连上校园 Wi-Fi（或插着校园网线），"
                "然后回到窗口再点一次「立即重新认证」。")
    if isinstance(exc, ValueError):
        return ("本机的配置文件读不出来（可能被误改坏了）。\n\n"
                "点「账号设置」重新保存一遍账号密码，就能修复。")
    return ("程序遇到了一个没预料到的问题，你的账号信息不受影响。\n\n"
            "可以再试一次；如果反复出现，请把日志文件发给会电脑的人帮忙看看。")


# ---------------------------------------------------------------- 界面
class App:
    """一个窗口两块面板：主面板（日常用） + 设置面板（首次/改账号）。"""

    def __init__(self, root: "tk.Tk") -> None:  # noqa: F821
        self.root = root
        self.q: "queue.Queue[Tuple]" = queue.Queue()
        self.cfg = self._load_config()
        self._busy = False
        self._icon_ref: Any = None
        # 双击自动连接只做一次：连不上就交给用户看日志手动处理，
        # 不然状态刷新会让它无限重试
        self._auto_connect_done = False

        self._build_window()
        self._build_main()
        self._build_setup()
        self._build_log()

        self.root.after(80, self._poll_queue)
        self._spawn(self._job_state)
        if self._configured():
            self.show_main()
        else:
            self.show_setup(first_time=True)

    # ------------------------------------------------------------ 基础
    def _load_config(self) -> Config:
        try:
            return Config.load()
        except ValueError:
            cfg = Config()
            return cfg

    def _configured(self) -> bool:
        return bool(self.cfg.username) and bool(self.cfg.resolve_password(prompt=False))

    def _runner(self) -> Runner:
        def log(msg: str, level: str = "info") -> None:
            self.q.put(("log", msg, level))

        return Runner(self.cfg, logger=log)

    def _spawn(self, fn, *args) -> None:
        def safe() -> None:
            try:
                fn(*args)
            except Exception as exc:  # noqa: BLE001 - 线程里的错必须兜住
                detail = traceback.format_exc()
                path = _write_error_log(detail)
                self.q.put(("fatal", friendly_message(exc), detail, path))

        threading.Thread(target=safe, daemon=True).start()

    # ------------------------------------------------------------ 窗口骨架
    def _build_window(self) -> None:
        self.root.title("{} v{}".format(APP_TITLE, __version__))
        self.root.geometry("560x560")
        # 可缩放 + 设下限：小屏/高缩放本子上内容放得下放不下，用户都能自救
        self.root.resizable(True, True)
        self.root.minsize(420, 420)
        self.root.configure(bg=BG)
        try:
            from ._icon_data import ICON_PNG_B64
            self._icon_ref = self.root.tk.PhotoImage(data=base64.b64decode(ICON_PNG_B64))
            self.root.iconphoto(True, self._icon_ref)
        except Exception:  # noqa: BLE001 - 图标只是锦上添花
            pass

    def _label(self, parent, text: str = "", **kw) -> "tk.Label":  # noqa: F821
        kw.setdefault("bg", kw.pop("bg_", BG))
        kw.setdefault("fg", TEXT)
        kw.setdefault("font", FONT)
        kw.setdefault("anchor", "w")
        import tkinter as tk
        return tk.Label(parent, text=text, **kw)

    def _button(self, parent, text: str, command, kind: str = "normal") -> "tk.Button":  # noqa: F821
        import tkinter as tk
        colors = {
            "primary": (BLUE, "#ffffff"),
            "normal": (GRAY_BTN, TEXT),
            "danger": (GRAY_BTN, RED),
        }
        bg, fg = colors.get(kind, colors["normal"])
        activebg = BLUE_DARK if kind == "primary" else "#d1d5db"

        def on_enter(_e=None) -> None:
            btn.configure(bg=activebg)

        def on_leave(_e=None) -> None:
            btn.configure(bg=bg)

        btn = tk.Button(parent, text=text, command=command, font=FONT_BOLD,
                        bg=bg, fg=fg, activebackground=activebg, activeforeground=fg,
                        relief="flat", cursor="hand2", padx=14, pady=6, bd=0)
        btn.bind("<Enter>", on_enter)
        btn.bind("<Leave>", on_leave)
        return btn

    # ------------------------------------------------------------ 主面板
    def _build_main(self) -> None:
        import tkinter as tk
        self.main_frame = tk.Frame(self.root, bg=BG)

        self.lbl_status = self._label(self.main_frame, "正在检查网络…",
                                      bg_=BG, font=FONT_TITLE)
        self.lbl_status.pack(pady=(22, 0))
        self.lbl_detail = self._label(self.main_frame, "", bg_=BG,
                                      fg=MUTED, font=FONT_SMALL)
        self.lbl_detail.pack(pady=(0, 10))

        card = tk.Frame(self.main_frame, bg=CARD, padx=16, pady=12,
                        highlightbackground="#e5e7eb", highlightthickness=1)
        card.pack(fill="x", padx=24)
        self.info_vars: Dict[str, "tk.Label"] = {}  # noqa: F821
        for row, (key, title) in enumerate((
                ("username", "上网账号"),
                ("password", "密码"),
                ("carrier", "运营商"),
                ("portal", "认证门户"),
                ("autostart", "开机自启"))):
            self._label(card, title, bg_=CARD, fg=MUTED, font=FONT_SMALL)\
                .grid(row=row, column=0, sticky="w", pady=2)
            val = self._label(card, "…", bg_=CARD, font=FONT)
            val.grid(row=row, column=1, sticky="w", padx=(18, 0), pady=2)
            card.grid_columnconfigure(1, weight=1)
            self.info_vars[key] = val

        btns = tk.Frame(self.main_frame, bg=BG)
        btns.pack(fill="x", padx=24, pady=14)
        self.btn_connect = self._button(btns, "立即重新认证",
                                        lambda: self.connect(force=True), "primary")
        self.btn_connect.pack(side="left")
        self.btn_health = self._button(btns, "一键体检", self.health_check)
        self.btn_health.pack(side="left", padx=(10, 0))
        self.btn_setup = self._button(btns, "账号设置…",
                                      lambda: self.show_setup(first_time=False))
        self.btn_setup.pack(side="left", padx=(10, 0))
        self.btn_autostart = self._button(btns, "开机自启", self.toggle_autostart)
        self.btn_autostart.pack(side="left", padx=(10, 0))

    # ------------------------------------------------------------ 设置面板
    def _build_setup(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.setup_frame = tk.Frame(self.root, bg=BG)

        # 表单比窗口高时（小屏 / 150% 缩放的本子）必须能滚动，否则填不到底。
        # 滚轮在 show_setup 里绑定、切走时解绑，避免劫持日志区的滚动。
        canvas = tk.Canvas(self.setup_frame, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(self.setup_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BG)
        canvas.create_window((0, 0), window=inner, anchor="nw", tags="inner")
        inner.bind("<Configure>",
                   lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda _e: canvas.itemconfigure("inner", width=_e.width))
        self._setup_canvas = canvas
        self._setup_inner = inner

        def _wheel(e) -> None:
            step = -1 if getattr(e, "delta", 0) > 0 else 1
            canvas.yview_scroll(step, "units")

        self._setup_wheel = _wheel

        head = self._label(inner, "填写上网信息",
                           bg_=BG, font=FONT_TITLE)
        head.pack(pady=(22, 2))
        self._label(inner, "只需要填一次，以后开机就会自动连。",
                    bg_=BG, fg=MUTED, font=FONT_SMALL).pack(pady=(0, 10))

        card = tk.Frame(inner, bg=CARD, padx=18, pady=14,
                        highlightbackground="#e5e7eb", highlightthickness=1)
        card.pack(fill="x", padx=24)

        self.var_username = tk.StringVar()
        self.var_password = tk.StringVar()
        self.var_show_pw = tk.BooleanVar(value=False)
        self.var_ssid = tk.StringVar()
        self.var_autostart = tk.BooleanVar(value=True)

        def field(row: int, title: str, widget, hint: str = "") -> None:
            self._label(card, title, bg_=CARD, font=FONT_BOLD)\
                .grid(row=row, column=0, sticky="w", pady=(8, 2))
            widget.grid(row=row + 1, column=0, sticky="ew", pady=(0, 2))
            card.grid_rowconfigure(row + 1, weight=0)
            if hint:
                self._label(card, hint, bg_=CARD, fg=MUTED, font=FONT_SMALL)\
                    .grid(row=row + 2, column=0, sticky="w", pady=(0, 4))

        ent_user = ttk.Entry(card, textvariable=self.var_username, font=FONT)
        field(0, "上网账号（一般是学号）", ent_user,
              "学校发的上网账号。不确定的话，试试学号本身。")

        ent_pw = ttk.Entry(card, textvariable=self.var_password, font=FONT,
                           show="●")
        field(3, "上网密码", ent_pw, "就是登录校园网认证页面时用的那个密码。")

        chk_show = ttk.Checkbutton(card, text="显示密码", variable=self.var_show_pw,
                                   command=lambda: ent_pw.configure(
                                       show="" if self.var_show_pw.get() else "●"))
        chk_show.grid(row=5, column=0, sticky="w", pady=(0, 2))

        self.carrier_map: Dict[str, str] = {}
        for code, label_text in list(carrier.CHOICES) + list(carrier.EXTRA_CHOICES):
            self.carrier_map[label_text] = code
        combo = ttk.Combobox(card, font=FONT, state="readonly",
                             values=list(self.carrier_map))
        combo.current(0)
        self.var_carrier_widget = combo
        field(6, "宽带运营商", combo, "手机卡是哪家就选哪家；校园网套餐选第一项。")

        ent_ssid = ttk.Entry(card, textvariable=self.var_ssid, font=FONT)
        field(9, "校园 Wi-Fi 名称（可留空）", ent_ssid,
              "填了它，电脑没连上校园 Wi-Fi 时会自动帮你切过去。")

        chk_auto = ttk.Checkbutton(card, text="开机自动登录（推荐）",
                                   variable=self.var_autostart)
        chk_auto.grid(row=12, column=0, sticky="w", pady=(8, 0))
        card.grid_columnconfigure(0, weight=1)

        self.lbl_setup_error = self._label(inner, "", bg_=BG,
                                           fg=RED, font=FONT_SMALL)
        self.lbl_setup_error.pack(fill="x", padx=26, pady=(8, 0))

        btns = tk.Frame(inner, bg=BG)
        btns.pack(fill="x", padx=24, pady=10)
        self.btn_save = self._button(btns, "保存并立即连接", self.save_setup, "primary")
        self.btn_save.pack(side="left")
        self.btn_back = self._button(btns, "返回", self.show_main)
        self.btn_back.pack(side="left", padx=(10, 0))
        self._hint_stored = self._label(
            inner, "", bg_=BG, fg=MUTED, font=FONT_SMALL)
        self._hint_stored.pack(fill="x", padx=26, pady=(2, 10))

    # ------------------------------------------------------------ 日志区
    def _build_log(self) -> None:
        import tkinter as tk
        # 注意：这里只构建不布局 —— 布局在 show_main / show_setup 里切换。
        # 设置页有滚动表单，日志框挤在里面纯属浪费屏幕（截图反馈过），
        # 只在主面板显示。
        wrap = tk.Frame(self.root, bg=BG)
        self.log_wrap = wrap
        self.log_box = tk.Text(wrap, height=9, font=FONT_SMALL, relief="flat",
                               bg=CARD, fg=TEXT, state="disabled", wrap="word",
                               highlightbackground="#e5e7eb", highlightthickness=1,
                               padx=10, pady=8)
        self.log_box.pack(fill="both", expand=True)
        self.log_box.pack(fill="both", expand=True)
        for tag, color in (("info", MUTED), ("ok", GREEN),
                           ("warn", "#b45309"), ("error", RED), ("debug", "#9ca3af")):
            self.log_box.tag_configure(tag, foreground=color)

    # ------------------------------------------------------------ 显示切换
    def show_main(self) -> None:
        self.setup_frame.pack_forget()
        try:  # 设置页的滚轮劫持解绑（Text 自己有原生滚动）
            self.root.unbind_all("<MouseWheel>")
        except Exception:  # noqa: BLE001
            pass
        self.log_wrap.pack(fill="both", expand=True, padx=24, pady=(6, 14))
        self.main_frame.pack(fill="both", expand=True)
        self._spawn(self._job_state)

    def show_setup(self, first_time: bool = False) -> None:
        self.main_frame.pack_forget()
        self.log_wrap.pack_forget()  # 表单要地方，日志回主面板再看
        self.setup_frame.pack(fill="both", expand=True)
        self.root.bind_all("<MouseWheel>", self._setup_wheel)
        self.lbl_setup_error.configure(text="")
        self.var_username.set(self.cfg.username or "")
        self.var_password.set("")
        self.var_ssid.set(self.cfg.wifi_ssid or "")
        code = self.cfg.options.get("carrier") or "campus"
        for label_text, c in self.carrier_map.items():
            if c == code:
                self.var_carrier_widget.set(label_text)
                break
        self._hint_stored.configure(text="" if not self.cfg.username
                                    else "密码留空表示沿用已保存的密码。")
        self.btn_back.configure(
            text="返回" if self.cfg.username else "",
            command=self.show_main if self.cfg.username else (lambda: None))
        if first_time or not self.var_ssid.get():
            self._spawn(self._job_prefill_ssid)
        self._fit_window_to_setup()

    def _fit_window_to_setup(self) -> None:
        """窗口高度尽量迁就表单：装得下就撑到内容高，装不下就到屏幕底
        （剩下的靠滚动）。宽度不动，尊重用户自己拖出来的尺寸。"""
        self.root.update_idletasks()
        # 画布自己是「视口」，reqheight 不反映内容 —— 要问 inner frame
        need = self._setup_inner.winfo_reqheight() + 40  # 40 ≈ 标题栏等边角
        screen = self.root.winfo_screenheight()
        target = max(420, min(need, screen - 80))
        width = self.root.winfo_width() or 560
        self.root.geometry("{}x{}".format(width, target))

    # ------------------------------------------------------------ 队列与刷新
    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self.q.get_nowait()
                self._dispatch(msg)
        except queue.Empty:
            pass
        except Exception as exc:  # noqa: BLE001 - 刷新循环绝不能死
            _write_error_log(traceback.format_exc())
            sys.stderr and sys.stderr.write("gui loop error: {}\n".format(exc))
        self.root.after(80, self._poll_queue)

    def _dispatch(self, msg: Tuple) -> None:
        kind = msg[0]
        if kind == "log":
            self._append_log(msg[1], msg[2])
        elif kind == "state":
            self._apply_state(msg[1])
        elif kind == "busy":
            self._set_busy(msg[1], msg[2])
        elif kind == "connect":
            self._on_connect_done(msg[1], msg[2], msg[3])
        elif kind == "health":
            self._on_health(msg[1])
        elif kind == "fatal":
            from tkinter import messagebox
            text = msg[1]
            if msg[3]:
                text += "\n\n日志文件：{}".format(msg[3])
            messagebox.showerror(APP_TITLE, text, parent=self.root)
            self._set_busy(False, "")
        elif kind == "prefill":
            if msg[1].get("ssid") and not self.var_ssid.get():
                self.var_ssid.set(msg[1]["ssid"])
        elif kind == "autostart_done":
            self._append_log(msg[1], "info")
            self._spawn(self._job_state)
        elif kind == "saved":
            self.show_main()
            self.connect(force=True)

    def _append_log(self, text: str, level: str = "info") -> None:
        from tkinter import TclError
        try:
            self.log_box.configure(state="normal")
            stamp = datetime.datetime.now().strftime("%H:%M:%S")
            self.log_box.insert("end", "{}  {}\n".format(stamp, text), (level,))
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        except TclError:
            pass

    def _set_busy(self, busy: bool, text: str) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        for btn in (self.btn_connect, self.btn_health, self.btn_setup,
                    self.btn_autostart, self.btn_save):
            try:
                btn.configure(state=state)
            except Exception:  # noqa: BLE001
                pass
        if text:
            self._append_log(text, "info")

    # ------------------------------------------------------------ 后台任务
    def _job_state(self) -> None:
        cfg = self.cfg
        data: Dict[str, Any] = {
            "online": None,
            "detail": "",
            "username": cfg.username or "未设置",
            "password_source": "",
            "carrier": "未设置",
            "portal": cfg.portal_ip or "自动探测",
            "autostart": autostart.status().startswith("已安装"),
            "configured": self._configured(),
        }
        # 老版本图形版写坏过自启命令（误带 -m campusnet，重启即崩）：
        # 打包版检测到就自动重写一次，用户不用手动关了再开
        if data["autostart"] and getattr(sys, "frozen", False) \
                and "-m campusnet" in autostart.status():
            autostart.install()
            data["autostart"] = autostart.status().startswith("已安装")
            self.q.put(("log", "检测到旧版写入的开机自启命令有问题，已自动修正", "ok"))
        pw = cfg.resolve_password(prompt=False)
        data["password_source"] = cfg.password_source if pw else ""
        code = cfg.options.get("carrier")
        if code and carrier.is_known(code):
            data["carrier"] = carrier.label(code)
        try:
            st = self._runner().status()
            data["online"] = st.online
            data["detail"] = st.describe()
        except Exception as exc:  # noqa: BLE001
            data["online"] = False
            data["detail"] = "网络检查失败：{}".format(exc)
        self.q.put(("state", data))

    def _job_prefill_ssid(self) -> None:
        ssid = _wifi.current_ssid() or ""
        self.q.put(("prefill", {"ssid": ssid}))

    def _job_connect(self, force: bool) -> None:
        cfg = self.cfg
        runner = self._runner()
        self.q.put(("busy", True, "正在连接校园网…"))
        try:
            result = runner.ensure_online(force=force)
        finally:
            self.q.put(("busy", False, ""))
        # 首次运行自动初始化：把探测到的门户地址记进配置
        if result.ok and result.detection and result.detection.portal \
                and not cfg.portal_ip:
            cfg.portal_ip = result.detection.portal
            try:
                cfg.save()
                self.q.put(("log", "已记住认证门户地址，下次连接更快", "ok"))
            except Exception:  # noqa: BLE001
                pass
        attempts = "\n".join(a.short() for a in result.attempts)
        self.q.put(("connect", result.ok, result.message, attempts))

    def _job_health(self) -> None:
        cfg = self.cfg
        lines: List[str] = []
        pw = cfg.resolve_password(prompt=False)
        lines.append(("没问题" if cfg.username else "缺账号")
                     + "：上网账号" + ("" if cfg.username else "（先点「账号设置」填写）"))
        lines.append(("没问题，密码存在" + {
            "keyring": "系统凭据管理器",
            "config": "配置文件（明文，建议改用凭据管理器）",
            "env": "环境变量",
        }.get(cfg.password_source, "本机")) if pw else "缺密码（先点「账号设置」填写）")
        lines.append("开机自启：" + ("已开启" if autostart.status().startswith("已安装")
                                 else "未开启（可点主界面的「开机自启」按钮）"))
        if cfg.wifi_ssid:
            now = _wifi.current_ssid()
            lines.append("校园 Wi-Fi：{}（当前连的是：{}）".format(
                cfg.wifi_ssid, now or "没连 Wi-Fi"))
        st = self._runner().status()
        if st.online:
            lines.append("网络：已联网，一切正常")
        else:
            lines.append("网络：{}".format(st.describe()))
            det = self._runner().detect(st)
            if det.portal:
                lines.append("已找到认证门户：{}（识别为 {}）".format(
                    det.portal, det.best or "通用认证"))
                if det.portal != cfg.portal_ip and not cfg.portal_ip:
                    cfg.portal_ip = det.portal
                    try:
                        cfg.save()
                        lines.append("已把门户地址写进配置，下次更快")
                    except Exception:  # noqa: BLE001
                        pass
            else:
                lines.append("没探测到认证门户 —— 大概率没连上校园网。")
                lines.append("请先连上校园 Wi-Fi，再点一次「一键体检」。")
        self.q.put(("health", "\n".join(lines)))

    def _job_toggle_autostart(self) -> None:
        installed = autostart.status().startswith("已安装")
        text = autostart.uninstall() if installed else autostart.install()
        verb = "已关闭开机自启" if installed else "已开启开机自启"
        self.q.put(("autostart_done", "{}：{}".format(verb, text.splitlines()[0])))

    def _job_save_setup(self, username: str, password: str, carrier_code: str,
                        ssid: str, want_autostart: bool) -> None:
        cfg = self.cfg
        cfg.username = username
        cfg.options["carrier"] = carrier_code
        cfg.wifi_ssid = ssid
        stored_at = ""
        if password:
            if has_keyring() and _keyring_set(username, password):
                stored_at = "系统凭据管理器"
            else:
                cfg.password = password
                cfg.password_source = "config"
                cfg.save(include_password=True)
                stored_at = "配置文件（未装凭据组件，只能明文存放）"
            if not cfg.password:
                cfg.password_source = ""
        cfg.password_source = cfg.password_source or ""
        cfg.save()
        self.q.put(("log", "账号信息已保存" + ("（密码在{}）".format(stored_at)
                                if stored_at else ""), "ok"))
        if want_autostart:
            text = autostart.install()
            self.q.put(("log", "开机自启：" + text.splitlines()[0], "ok"))
        else:
            autostart.uninstall()
        self.q.put(("saved", None))

    # ------------------------------------------------------------ 按钮动作
    def connect(self, force: bool = True) -> None:
        if not self._configured():
            from tkinter import messagebox
            messagebox.showwarning(APP_TITLE, "还没有填账号密码，先点「账号设置」。",
                                   parent=self.root)
            return
        self._spawn(self._job_connect, force)

    def health_check(self) -> None:
        self._spawn(self._job_health)

    def toggle_autostart(self) -> None:
        self._spawn(self._job_toggle_autostart)

    def save_setup(self) -> None:
        username = self.var_username.get().strip()
        password = self.var_password.get()
        if not username:
            self.lbl_setup_error.configure(text="上网账号还没填 —— 一般就是你的学号。")
            return
        if not password and not self.cfg.resolve_password(prompt=False):
            self.lbl_setup_error.configure(text="密码还没填。就是连校园网时输的那个密码。")
            return
        ssid = self.var_ssid.get().strip()
        carrier_code = self.carrier_map.get(self.var_carrier_widget.get(), "campus")
        self._spawn(self._job_save_setup, username, password, carrier_code,
                    ssid, self.var_autostart.get())
        # 保存线程完成后会发 "saved" 消息，由它切回主界面并自动连接一次

    # ------------------------------------------------------------ 结果呈现
    def _apply_state(self, data: Dict[str, Any]) -> None:
        if data["online"] is True:
            self.lbl_status.configure(text="已连接，可以上网了", fg=GREEN)
        elif data["online"] is False:
            self.lbl_status.configure(text="还没连上校园网", fg=RED)
        else:
            self.lbl_status.configure(text="正在检查网络…", fg=TEXT)
        self.lbl_detail.configure(text=data.get("detail") or "")
        # 双击打开就应该自己连：已配置、没联网、还没自动试过 —— 来一次
        # （只试一次，失败不循环重试；用户要看详情/手动再来点「立即重新认证」）
        if (data.get("online") is False and data.get("configured")
                and not self._auto_connect_done and not self._busy):
            self._auto_connect_done = True
            self._append_log("检测到还没联网，自动帮你连接一次…", "info")
            self.connect(force=False)
        src = data.get("password_source") or ""
        pw_text = {
            "keyring": "已保存（系统凭据管理器）",
            "config": "已保存（配置文件，明文）",
            "env": "来自环境变量",
        }.get(src, "未设置")
        self.info_vars["username"].configure(text=data["username"])
        self.info_vars["password"].configure(text=pw_text)
        self.info_vars["carrier"].configure(text=data["carrier"])
        self.info_vars["portal"].configure(text=data["portal"])
        self.info_vars["autostart"].configure(
            text="已开启" if data["autostart"] else "未开启",
            fg=GREEN if data["autostart"] else MUTED)
        self.btn_autostart.configure(
            text="关闭自启" if data["autostart"] else "开启自启")

    def _on_connect_done(self, ok: bool, message: str, attempts: str) -> None:
        from tkinter import messagebox
        if ok:
            self._append_log(message, "ok")
            messagebox.showinfo(APP_TITLE, "连上了！可以正常上网了。\n\n" + message,
                                parent=self.root)
        else:
            self._append_log("认证没成功：{}".format(message), "error")
            text = ("这次没能连上校园网。\n\n"
                    "常见原因：\n"
                    "1. 密码输错了或刚改过密码 —— 点「账号设置」重新填一遍；\n"
                    "2. 还没连上校园 Wi-Fi —— 先连上再点「立即重新认证」；\n"
                    "3. 运营商选错了 —— 点「账号设置」换一个试试。\n\n"
                    "程序给出的原因：{}".format(message or "未知"))
            if attempts:
                text += "\n\n细节（给排障的人看的）：\n" + attempts
            messagebox.showerror(APP_TITLE, text, parent=self.root)
        self._spawn(self._job_state)

    def _on_health(self, text: str) -> None:
        from tkinter import messagebox
        messagebox.showinfo("体检结果", text, parent=self.root)


# ---------------------------------------------------------------- 入口
def _run_cli_passthrough(argv: List[str]) -> int:
    from .cli import main as cli_main
    return cli_main(argv)


def run(argv: Optional[List[str]] = None) -> int:
    """GUI 入口。带命令行参数时转给 CLI（方便排障），否则开窗口。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        return _run_cli_passthrough(argv)

    if os.name == "nt":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001 - 老系统没有这个 API
            pass

    try:
        import tkinter as tk
        from tkinter import messagebox  # noqa: F401
    except Exception:  # noqa: BLE001
        detail = traceback.format_exc()
        path = _write_error_log(detail)
        text = ("窗口界面打不开：系统缺少图形组件（tkinter）。\n\n"
                "这通常说明 Python 安装不完整。请重新安装 Python，"
                "安装时勾选「tcl/tk and IDLE」。\n")
        if path:
            text += "\n技术细节已保存到：{}".format(path)
        _fallback_msgbox(APP_TITLE, text)
        return 1

    # --noconsole 打包后 stdout/stderr 是 None，print 会崩，换成黑洞
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115

    root = tk.Tk()
    app = App(root)

    def report_exception(exc_type, exc, tb) -> None:  # noqa: ANN001
        detail = "".join(traceback.format_exception(exc_type, exc, tb))
        path = _write_error_log(detail)
        text = friendly_message(exc)
        if path:
            text += "\n\n日志文件：{}".format(path)
        try:
            from tkinter import messagebox
            messagebox.showerror(APP_TITLE, text, parent=root)
        except Exception:  # noqa: BLE001
            _fallback_msgbox(APP_TITLE, text)

    root.report_callback_exception = report_exception

    smoke = os.environ.get(SMOKE_ENV, "")
    if smoke:
        try:
            parts = smoke.split(",")
            delay = max(0.5, float(parts[0]))
            if len(parts) > 1 and parts[1] == "setup":
                app.show_setup(first_time=False)
            root.after(int(delay * 1000), root.destroy)
        except Exception:  # noqa: BLE001
            pass

    root.mainloop()
    return 0


def _fallback_msgbox(title: str, text: str) -> None:
    """tkinter 都没有时的最后防线：直接调 Win32 弹窗。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
    except Exception:  # noqa: BLE001
        sys.stderr and sys.stderr.write("{}: {}\n".format(title, text))
