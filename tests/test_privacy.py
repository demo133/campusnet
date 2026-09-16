"""守住仓库里不再混进个人隐私信息。

这个测试是**回归护栏**，不是功能测试。起因很具体：项目早期把作者自己的
真实学号、门户 IP、校园 Wi-Fi 名字当成"示例值"写进了文档和测试，
后来要开源分发了才发现这些东西散落在十几个文件里 —— 靠人肉 grep 是靠不住的。

所以这里把"不许出现"的东西固化成断言：**只要有人再把这些值写回来，
本地 pytest 就会红，不用等推到 GitHub 才发现。**

要新增/修改被盯的值，改 ``FORBIDDEN`` 即可。
"""

import os
import re

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _unhex(encoded):
    """把十六进制还原成真实值。

    刻意**不写明文**：明文一旦出现在本文件里，``git grep`` 之类的工具
    会在这里命中一条"隐私泄漏"，而且本文件自己也会被下面那条断言判红。
    用十六进制的好处是语义明确、可读可查，却不含任何可被直接 grep 到的字面量。
    """
    return bytes.fromhex(encoded).decode("utf-8")


#: 绝不允许出现在仓库任何文本文件里的具体值（都是**真实值**，不是占位符）。
#: 占位符（如 ``2200000000`` / ``10.99.0.1`` / ``CampusWiFi``）是允许的。
FORBIDDEN = {
    "真实学号": _unhex("32303234313232333034"),
    "真实门户 IP": _unhex("3231302e32382e33392e323530"),
    "校园 Wi-Fi 名": _unhex("4a4f55"),
    "学校全名": _unhex("e6b19fe88b8fe6b5b7e6b48be5a4a7e5ada6"),
    "他人 Wi-Fi 名": _unhex("e6809de9bd90e4b88de68c82e7a791"),
    "本机私网 IP": _unhex("31302e32302e33302e31"),
    # ---- 本机网络与硬件指纹（从本机 ipconfig / netsh 抓下来的真实值） ----
    "本机网卡 MAC": _unhex("30343a65633a64383a65663a61343a6163"),
    "宿舍 AP BSSID": _unhex("37343a34643a36643a37373a62663a3130"),
    "本机网卡 GUID": _unhex(
        "31633037393138662d646331622d343037362d626166362d393431653266656437656435"
    ),
    "本机无线网卡型号": _unhex("496e74656c2852292057692d46692036204158323031"),
}

#: 文本文件才检查；二进制产物（zip / 图片）不在这里管。
TEXT_EXT = {".md", ".py", ".sh", ".json", ".txt", ".yml", ".yaml", ".html", ".toml"}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", "dist"}

#: 文档里出现的连续数字串。**长度 ≥10 的全数字串**通常就是没打码的学号，
#: 值得人看一眼；测试代码里有大量伪造账号，所以只扫文档。
_LONG_DIGITS = re.compile(r"\b\d{10,}\b")
#: 允许出现的合法长数字：占位学号、Dr.COM 的协议常量。
_ALLOWED_DIGITS = {"2200000000", "123456", "12345678", "000000000000"}  # 最后一个是 eportal 文档示例里的全零 MAC

#: 内部标记与工具品牌名：它们会暴露"这份东西是怎么做出来的"，
#: 而且品牌名还会把使用者绑在某个特定产品上。
#:
#: **全部用十六进制写** —— 明文写在这个文件里，它自己就会被下面那条断言判红。
_FORBIDDEN_KEYS = (
    _unhex("6167656e745f63726561746564"),  # skill 元数据里的内部标记键
    _unhex("776f726b6275646479"),
    _unhex("636f64656275646479"),
    _unhex("636c61756465"),
    _unhex("636f70696c6f74"),
    _unhex("63686174677074"),
)


def _bounded(token: str) -> str:
    """把短词包成"两侧不能是英文字母"的模式。

    ``AI`` 这种两字母词**不能按子串匹配**：那会命中 ``main`` / ``email`` /
    ``domain`` / ``detail`` 之类的普通单词，断言立刻退化成噪音，
    而没人会再认真看一条满屏误报的断言。
    """
    return r"(?<![A-Za-z]){}(?![A-Za-z])".format(re.escape(token))


#: 不该出现在仓库任何位置的词汇（同样十六进制写，见 ``_FORBIDDEN_KEYS``）。
_FORBIDDEN_TERMS = (
    _bounded(_unhex("4149")),                    # 两字母缩写，必须按词边界匹配
    _unhex("e4babae5b7a5e699bae883bd"),          # 中文全称
    _unhex("e5a4a7e6a8a1e59e8b"),
    _bounded(_unhex("4c4c4d")),
    _bounded(_unhex("475054")),
)


def _text_files():
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if os.path.splitext(name)[1].lower() not in TEXT_EXT:
                continue
            path = os.path.join(dirpath, name)
            yield path, os.path.relpath(path, REPO).replace(os.sep, "/")


@pytest.mark.parametrize("label", sorted(FORBIDDEN))
def test_no_real_personal_value_in_repo(label):
    """这些真实值一个都不许留在仓库里。"""
    needle = FORBIDDEN[label]
    offenders = []
    for path, rel in _text_files():
        text = open(path, encoding="utf-8", errors="replace").read()
        if needle in text:
            offenders.append(rel)
    assert not offenders, (
        "{}（`{}`）又出现在这些文件里了：\n  {}".format(
            label, needle, "\n  ".join(sorted(offenders))
        )
    )


def test_no_unexpected_long_digit_run():
    """文档里的长数字串要人过一眼 —— 大概率就是漏打码的账号。

    测试代码里有大量伪造账号，所以只扫``doc``与顶层说明文件。
    """
    suspicious = []
    for path, rel in _text_files():
        if not (rel.startswith("docs/") or rel in ("README.md", "CHANGELOG.md")):
            continue
        text = open(path, encoding="utf-8", errors="replace").read()
        for match in _LONG_DIGITS.findall(text):
            if match not in _ALLOWED_DIGITS:
                suspicious.append("{}: {}".format(rel, match))
    assert not suspicious, "文档里出现了未打码的长数字串：\n  " + "\n  ".join(suspicious)


@pytest.mark.parametrize("needle", _FORBIDDEN_KEYS)
def test_no_internal_marker(needle):
    """不许出现内部标记键或工具品牌名。

    前一个是 skill 的元数据键，会把"这份文件是怎么生成的"原样带到用户机器上；
    后几个是产品名 —— 既暴露制作方式，也把使用者绑在某个特定产品上。

    这个测试本身要检查这些词，所以**跳过自己**。
    """
    offenders = _scan_substring(needle)
    assert not offenders, "`{}` 出现在这些文件里了：\n  {}".format(
        needle, "\n  ".join(sorted(offenders))
    )


@pytest.mark.parametrize("pattern", _FORBIDDEN_TERMS)
def test_no_tool_wording(pattern):
    """文档里也不该出现描述"AI 工具"的词。

    这条是**字面**要求：仓库对外呈现的应该是这个工具本身，
    而不是它是用什么做出来的、或者绑定在哪家产品上。
    """
    offenders = _scan_regex(pattern)
    assert not offenders, "`{}` 出现在这些文件里了：\n  {}".format(
        pattern, "\n  ".join(sorted(offenders))
    )


def _scan_substring(needle: str):
    """全仓库文本文件里按子串找 ``needle``，跳过本文件。"""
    return _scan(lambda text: needle in text.lower())


def _scan_regex(pattern: str):
    """同上，但按正则找（用于必须按词边界匹配的短词）。"""
    regex = re.compile(pattern)
    return _scan(lambda text: bool(regex.search(text)))


def _scan(match):
    me = os.path.basename(__file__)
    offenders = []
    for path, rel in _text_files():
        # 护栏自己带着这些"要找的东西"，必须跳过，否则永远红
        if os.path.basename(path) == me:
            continue
        text = open(path, encoding="utf-8", errors="replace").read()
        if match(text):
            offenders.append(rel)
    return offenders


def test_skill_frontmatter_has_no_internal_keys():
    """两个 SKILL.md 的 frontmatter 只该有 ``name`` / ``description``。

    平台的 skill 规范只认这两个键；多出来的内部键会被原样带到用户机器上。
    """
    for rel in ("skill/campusnet/SKILL.md", "skill/redskill/SKILL.md"):
        path = os.path.join(REPO, rel.replace("/", os.sep))
        lines = open(path, encoding="utf-8").read().splitlines()
        assert lines[0] == "---", "{} 没有 frontmatter".format(rel)
        end = lines.index("---", 1)
        keys = {line.split(":", 1)[0].strip() for line in lines[1:end] if line.strip()}
        extra = keys - {"name", "description"}
        assert not extra, "{} 的 frontmatter 多了内部键：{}".format(rel, sorted(extra))


def test_shipped_skill_package_is_clean():
    """打好的包里也不能有 —— 那是最容易被外人拿到的一份。"""
    import zipfile

    regexes = [re.compile(p) for p in _FORBIDDEN_TERMS]
    zip_path = os.path.join(REPO, "skill", "dist", "campusnet-redskill.zip")
    if not os.path.exists(zip_path):
        pytest.skip("还没打包，先跑 python skill/build_redskill.py")
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            text = zf.read(name).decode("utf-8", "replace")
            for label, needle in FORBIDDEN.items():
                assert needle not in text, "{} 里的 {} 没清干净：{}".format(
                    zip_path, label, name
                )
            for needle in _FORBIDDEN_KEYS:
                assert needle not in text.lower(), "{} 里带了 `{}`：{}".format(
                    zip_path, needle, name
                )
            for regex in regexes:
                assert not regex.search(text), "{} 里有 `{}`：{}".format(
                    zip_path, regex.pattern, name
                )
