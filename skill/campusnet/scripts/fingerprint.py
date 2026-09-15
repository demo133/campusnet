#!/usr/bin/env python3
"""采集一份**自动脱敏**的校园网指纹报告，可直接粘贴到 issue。

这个项目最缺的是不同学校的真实指纹。手动打码容易漏，所以做成脚本。

用法::

    python fingerprint.py                # 输出到屏幕，并存一份到当前目录
    python fingerprint.py --keep-subnet  # 保留 IP 前两段（默认全打码）
    python fingerprint.py --no-save      # 只打印，不落盘

脱敏覆盖：IPv4、MAC、密码字段、连续 6 位以上的数字（学号）。
**仍然建议自己再看一遍**再发出去 —— 自动脱敏覆盖常见形态，不保证零遗漏。
"""

import argparse
import os
import re
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_RUN = os.path.join(_HERE, "run.py")

_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_MAC = re.compile(r"\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b")
_DIGITS = re.compile(r"\b\d{6,}\b")
#: 形如 upass=xxx / password=xxx / CAMPUSNET_PASSWORD=xxx 的赋值
_SECRET = re.compile(
    r"(?i)\b(upass|password|passwd|pass|pwd|CAMPUSNET_PASSWORD)(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s&\"'#,;]+)"
)
#: 这些键的取值是协议常量（协议固定值 / 参数编号），不是个人信息，
#: 打码反而把报告变得没法看（``0MKKey=123456`` 变成 ``12****``）。
#: 先把它们换成占位符，掩码跑完再还原。
_SAFE_KEYS = ("0MKKey", "ac_id", "r1", "r2", "r3", "r6", "para", "n", "type", "v")
_SAFE_ASSIGN = re.compile(
    r"(?i)\b(" + "|".join(_SAFE_KEYS) + r")(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)"
)

#: 输出里带全角冒号（``Server：DrcomServer1.0``），所以关键词匹配前要先归一化。
#: 这是**兜底**用的 —— 首选直接读 ``detect`` 给出的指纹评分。
_HINTS = (
    ("drcom", "drcomserver"),
    ("drcom", "dr.comweblogin"),
    ("drcom", "ddddd"),
    ("srun", "srun_portal"),
    ("srun", "rad_user_info"),
    ("ruijie", "ruijie"),
    ("eportal", "acsetting"),
)

#: 形如 ``•   drcom      1.00  Dr.COM 城市热点``
_RANK_LINE = re.compile(r"^\s*[•·*]\s+(\S+)\s+([0-9]+(?:\.[0-9]+)?)\s+\S")


def _detected_systems(text):
    """读出认证系统，按可信度排序。

    优先解析 ``detect`` 已经算好的指纹评分 —— 那才是权威结果，
    自己再拿关键词猜一遍只会得出更差的答案（而且容易漏，
    比如分高的 drcom 没匹配上、分低的 eportal 反而匹配上了）。
    """
    ranked = []
    for line in (text or "").splitlines():
        match = _RANK_LINE.match(line)
        if match:
            name, score = match.group(1), float(match.group(2))
            if score > 0 and name not in [n for n, _ in ranked]:
                ranked.append((name, score))
    if ranked:
        return [name for name, _ in sorted(ranked, key=lambda kv: -kv[1])]

    # 兜底：输出里没有评分（比如 detect 失败了），退回关键词
    low = (text or "").lower().replace("：", ":")
    hits = []
    for name, needle in _HINTS:
        if needle in low and name not in hits:
            hits.append(name)
    return hits


def _mask_ip(match, keep_subnet):
    if keep_subnet:
        parts = match.group(0).split(".")
        return "{}.{}.x.x".format(parts[0], parts[1])
    return "x.x.x.x"


def redact(text, keep_subnet=False):
    text = _SECRET.sub(lambda m: "{}{}******".format(m.group(1), m.group(2)), text)
    text = _MAC.sub("xx:xx:xx:xx:xx:xx", text)
    text = _IPV4.sub(lambda m: _mask_ip(m, keep_subnet), text)

    # 把协议常量先摘出去：它们里面也有长数字，掩码会误伤
    stash = []

    def _stash(match):
        stash.append(match.group(0))
        return "\x00{}\x00".format(len(stash) - 1)

    text = _SAFE_ASSIGN.sub(_stash, text)

    def _digits(match):
        s = match.group(0)
        return s[:2] + "*" * (len(s) - 2)

    text = _DIGITS.sub(_digits, text)

    for index, original in enumerate(stash):
        text = text.replace("\x00{}\x00".format(index), original)
    return text


def _run(args):
    proc = subprocess.run(
        [sys.executable, _RUN] + args,
        capture_output=True,
        text=True,
        errors="replace",
    )
    return proc.returncode, (proc.stdout or ""), (proc.stderr or "")


def main(argv=None):
    parser = argparse.ArgumentParser(description="采集脱敏后的校园网指纹报告")
    parser.add_argument(
        "--keep-subnet",
        action="store_true",
        help="保留 IP 前两段（默认全部打码）",
    )
    parser.add_argument("--no-save", action="store_true", help="不写文件，只打印")
    args = parser.parse_args(argv)

    rc_detect, out_detect, err_detect = _run(["detect", "--verbose"])
    rc_doctor, out_doctor, err_doctor = _run(["doctor"])

    systems = _detected_systems(out_detect)

    blocks = [
        "## campusnet 指纹报告",
        "",
        "> 账号、IP、MAC、密码已自动打码。提交前请自行再检查一遍。",
        "",
        "### 平台",
        "",
        "- Python：{}".format(sys.version.split()[0]),
        "- 系统：{}".format(sys.platform),
    ]

    # 路由器用户能读到这个文件，桌面端读不到属正常
    for path in ("/etc/openwrt_release",):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                content = fh.read().strip()
            if content:
                blocks += ["", "### {}".format(path), "", "```", content, "```"]
        except OSError:
            pass

    if systems:
        blocks += ["", "### 疑似认证系统", "", "、".join(systems), ""]

    for title, rc, out, err in (
        ("detect --verbose", rc_detect, out_detect, err_detect),
        ("doctor", rc_doctor, out_doctor, err_doctor),
    ):
        body = redact(out or "", args.keep_subnet).strip()
        if not body:
            body = "（无输出，退出码 {}）".format(rc)
        blocks += ["", "### {}".format(title), "", "```", body, "```"]
        if err.strip():
            blocks += [
                "",
                "<details><summary>stderr</summary>",
                "",
                "```",
                redact(err, args.keep_subnet).strip(),
                "```",
                "",
                "</details>",
            ]

    report = "\n".join(blocks).rstrip() + "\n"
    print(report)

    if not args.no_save:
        path = os.path.abspath("campusnet-fingerprint.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(report)
        sys.stderr.write("\n已保存到 {}\n".format(path))

    return 0


if __name__ == "__main__":
    sys.exit(main())
