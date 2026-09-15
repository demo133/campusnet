"""测试公共夹具：一个假的 HTTP 会话，用来断言「我们到底发了什么请求」。

这类工具最容易出错的地方不是加密，而是**请求拼错**（字段名、端口、顺序）。
所以单元测试的重点放在"请求长什么样"，而不是端到端打真服务器。
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from campusnet.providers.base import DetectContext  # noqa: E402
from campusnet.session import Response  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as fh:
        return fh.read()


def make_response(body: str = "", status: int = 200, headers: dict = None, url: str = "") -> Response:
    return Response(
        status=status,
        headers=headers or {},
        body=body.encode("utf-8"),
        url=url,
    )


class FakeSession:
    """按 URL 子串匹配返回值，并记录所有请求。"""

    def __init__(self, routes=None, default: Response = None) -> None:
        self.routes = list(routes or [])
        self.default = default or make_response("", status=404)
        self.calls = []

    # --- 用于断言
    @property
    def urls(self):
        return [call[1] for call in self.calls]

    def last(self, method: str = None):
        for call in reversed(self.calls):
            if method is None or call[0] == method:
                return call
        return None

    def find(self, needle: str):
        for call in self.calls:
            if needle in call[1]:
                return call
        return None

    # --- Session 接口
    def _resolve(self, url: str) -> Response:
        for matcher, response in self.routes:
            if callable(matcher):
                if matcher(url):
                    return response
            elif matcher in url:
                return response
        return self.default

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, None))
        return self._resolve(url)

    def post(self, url, data=None, **kwargs):
        self.calls.append(("POST", url, data))
        return self._resolve(url)

    def request(self, url, method="GET", data=None, **kwargs):
        self.calls.append((method.upper(), url, data))
        return self._resolve(url)


@pytest.fixture
def drcom_page() -> str:
    return fixture("drcom_login_page.html")


@pytest.fixture
def ctx_drcom(drcom_page) -> DetectContext:
    return DetectContext(
        url="http://10.99.0.1/",
        text=drcom_page,
        headers={"server": "DrcomServer1.0"},
    )


# ---------------------------------------------------------------- CI 可诊断性
def pytest_runtest_logreport(report):
    """把断言失败发成 GitHub 的 **check-run annotation**。

    为什么需要这个：这个仓库的 job 日志**匿名读不到**（API 403），
    而 annotation 能通过公开 API 拿到：

        GET /repos/<o>/<r>/check-runs/<id>/annotations

    于是"只在某个平台上挂"的时候，不用登录也能看到**到底哪条断言红了**。
    这个价值是实打实的 —— 之前只知道「ubuntu 挂在 pytest」，
    却不知道挂在哪个用例上，只能靠猜。

    （workflow 里原本想用 ``$GITHUB_STEP_SUMMARY`` 达到同样目的，
    但实测 ``check-runs/<id>.output.summary`` 取回来是空的，
    那条路走不通，改成 annotation。）

    只在 CI 上发，本地跑不会污染输出。
    """
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    if not report.failed or report.when != "call":
        return

    detail = (getattr(report, "longreprtext", "") or "").strip()
    # annotation 单条有长度上限，只保留最有信息量的尾部（断言那几行）
    tail = detail[-800:] if detail else "failed"
    # 工作流命令的格式要求，违反会被截断：
    #   1. 必须单行 —— 换行压成 " | "；
    #   2. `%` 要转义成 `%25` —— 断言里出现 `%3F`、`%E4%B8%AD`
    #      这类百分号编码是常事，不转义会被当成转义序列。
    single_line = " | ".join(line.strip() for line in tail.splitlines() if line.strip())
    print(
        "\n::error title=pytest 失败: {0}::{1}".format(
            report.nodeid, single_line.replace("%", "%25")
        ),
        flush=True,
    )
