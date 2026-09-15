"""运营商（ISP）选择。

很多学校的校园网在登录时不只填账号密码，还要先**选一个运营商**：

* **Dr.COM 城市热点** —— 页面上是「服务类型」四个单选项：
  校园用户 / 校园电信 / 校园联通 / 校园其他。它靠 ``R1`` / ``R3`` / ``para``
  三个隐藏字段区分，有的学校还要求账号带后缀（``@cmcc``）。
* **深澜 Srun** —— 靠 ``domain`` 参数区分（``@cmcc`` / ``@telecom`` /
  ``@unicom``），或者干脆是账号自带前后缀。
* **锐捷 / eportal** —— 通常没有独立字段，运营商体现在账号后缀上。

对用户来说这些都是「我该选移动还是电信」，所以这里统一成**一个概念**：
用户给一个运营商名字，由各 provider 自己翻译成该系统的参数。

设计要点
--------

用户能输入的东西五花八门：``移动`` / ``中国移动`` / ``cmcc`` / ``中国移动(CMCC)``。
所以 :func:`normalize` 做的是**尽力归一 + 认不出就原样保留**，
而不是 "匹配不上就报错" —— 认不出时把它当后缀用，往往正好是对的。
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

#: 归一化后的运营商代号 → 各种可能写法（都小写，用于匹配）
#:
#: 顺序：代号 → (中文别名, 英文别名)
ALIASES: Dict[str, Tuple[str, ...]] = {
    "campus": (
        "校园用户", "校园网", "校园", "校内", "本校", "教育网",
        "campus", "campusnet", "校园用户(默认)", "默认",
    ),
    # 注意：``校园电信`` / ``校园联通`` **不在这里**。
    # Dr.COM 页面上它们是独立的「服务类型」，靠 R1=1 / R3=1 区分，
    # 和纯运营商套餐（走账号后缀）不是一回事 —— 混在一起会让参数发错。
    # 它们由 drcom 模块的 SERVICE_ALIASES 单独处理。
    "cmcc": (
        "移动", "中国移动", "校园移动", "移动校园", "中国移动(CMCC)",
        "cmcc", "mobile", "china mobile",
    ),
    "telecom": (
        "电信", "中国电信", "校园电信(ChinaNet)", "china telecom",
        "chinatelecom", "telecom", "ct", "中国电信(CT)",
    ),
    "unicom": (
        "联通", "中国联通", "校园联通(ChinaUnicom)",
        "china unicom", "chinaunicom", "unicom", "cu",
    ),
    "other": (
        "其他", "其它", "校园其他", "校园其它", "other", "others",
    ),
    # Dr.COM 专属的两个「校园 + 运营商」混合档位。
    # 它们在页面上是独立选项，参数和纯运营商不同，所以单列成代号。
    "campus_telecom": (
        "校园电信", "校内电信", "校园电信(chinanet)",
    ),
    "campus_unicom": (
        "校园联通", "校内联通",
    ),
}

#: 代号 → 账号后缀（provider 没特别说明时的兜底）
DEFAULT_SUFFIX: Dict[str, str] = {
    "campus": "",
    "cmcc": "@cmcc",
    "telecom": "@telecom",
    "unicom": "@unicom",
    "other": "",
    "campus_telecom": "",
    "campus_unicom": "",
}

#: 代号 → 人类可读名字
LABELS: Dict[str, str] = {
    "campus": "校园用户（默认）",
    "cmcc": "中国移动",
    "telecom": "中国电信",
    "unicom": "中国联通",
    "other": "校园其他",
    "campus_telecom": "校园电信",
    "campus_unicom": "校园联通",
}

#: 给交互式向导用的选项（代号, 说明）
CHOICES: List[Tuple[str, str]] = [
    ("campus", "校园用户 / 校园网（默认，不确定就选这个）"),
    ("cmcc", "中国移动"),
    ("telecom", "中国电信"),
    ("unicom", "中国联通"),
    ("other", "校园其他 / 其它"),
]

#: 只有 Dr.COM 页面才会出现的额外选项。
#: 单独列出来是因为「校园电信」在 Dr.COM 上走 R1=1，
#: 和账号加 @telecom 后缀的纯电信套餐不是同一回事。
EXTRA_CHOICES: List[Tuple[str, str]] = [
    ("campus_telecom", "校园电信（Dr.COM 页面上的独立选项）"),
    ("campus_unicom", "校园联通（Dr.COM 页面上的独立选项）"),
]

#: 反查表：别名 → 代号
_LOOKUP: Dict[str, str] = {}
for _code, _names in ALIASES.items():
    for _name in _names:
        _LOOKUP[_name.lower()] = _code

#: ``中国移动(CMCC)`` 这种带括号注释的，把括号里的也当别名试一遍
_BRACKET = re.compile(r"[（(]\s*([^）)]*?)\s*[）)]")


def normalize(value: str) -> str:
    """把用户写的运营商归一成代号。

    认不出来就返回**去掉首尾空白的原文**（不报错）——
    因为很多学校的运营商是账号后缀，原样透传恰好是对的。

    这个函数必须**幂等**：``normalize('campus_telecom')`` 得原样返回，
    不能因为内部含 ``telecom`` 就被子串匹配成 ``telecom``。
    否则「校园电信」（Dr.COM 的 R1=1 档）会被降级成纯「电信」，
    参数发错、认证必然失败。
    """
    raw = (value or "").strip()
    if not raw:
        return ""

    # 已经是标准代号就直接返回（保证幂等）
    if raw in LABELS:
        return raw

    low = raw.lower()
    if low in _LOOKUP:
        return _LOOKUP[low]

    # 去掉括号注释再试一次：``中国移动(CMCC)`` → ``中国移动``
    stripped = _BRACKET.sub("", raw).strip().lower()
    if stripped in _LOOKUP:
        return _LOOKUP[stripped]

    # 括号里的内容本身也可能是代号：``校园宽带(移动)`` → ``移动``
    for inner in _BRACKET.findall(raw):
        inner = inner.strip().lower()
        if inner in _LOOKUP:
            return _LOOKUP[inner]

    # 子串包含：``中国移动校园宽带`` 含 ``移动``
    #
    # 按别名**长度从长到短**匹配 —— 否则 ``校园宽带(移动)`` 会先命中 ``校园``
    # 变成「校园用户」，而用户真正想说的是「移动」。长别名更具体，优先。
    # 同时要求别名不是纯 ASCII 单词的子串，避免 ``campus_telecom`` 命中 ``telecom``。
    for name in sorted(_LOOKUP, key=len, reverse=True):
        if len(name) < 2 or name not in low:
            continue
        # 纯 ASCII 别名要求出现在词边界上（``campus_telecom`` ≠ 含 ``telecom`` 词）
        if name.isascii() and low != name:
            continue
        return _LOOKUP[name]

    # 已经是 ``@xxx`` 形式，那就当后缀用
    return raw


def label(code: str) -> str:
    """代号 → 显示名。认不出的原样返回。"""
    return LABELS.get(code, code or "未指定")


def suffix_for(code: str, default: str = "") -> str:
    """这个运营商对应的账号后缀。

    已知代号用内置映射；认不出的（用户自填的）加上 ``@`` 前缀当后缀用，
    已经是 ``@xxx`` 的保持原样。
    """
    if not code:
        return default
    if code in DEFAULT_SUFFIX:
        return DEFAULT_SUFFIX[code]
    if code.startswith("@"):
        return code
    return "@" + code


def is_known(code: str) -> bool:
    return code in LABELS
