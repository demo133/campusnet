#!/usr/bin/env python3
"""把 skill 打包成「开源技能市场上传用」的 zip。

这类平台的上传门槛（来自平台《Skill 上传规范》+ 实测报错）：

1. **zip 解压后根目录直接是 SKILL.md**，不能套一层同名文件夹 ——
   平台认的就是根目录那个文件，套层就找不到。最容易踩的一条。
2. **SKILL.md 全文 ≤ 10000 字符**。注意是**字符**不是字节，
   而且是整个文件（不是表单里的简介字段）。中文一个字算一个字符。
3. **换行必须 LF**。CRLF 会让平台解析 frontmatter 失败，
   结果 name / description 直接变空，然后你查半天不知道错在哪。
4. **文件白名单只有 5 种**：``.md .py .js .json .txt``。
   ``.png .svg .yaml .gitignore .LICENSE`` 全会被拒。
   （``.py`` 是**允许**的 —— 早先有教程说"Python 脚本传不了"，
   那是错的；实测报错里的白名单明确包含 .py。）
5. 单文件 ≤ 10MB，总大小 ≤ 30MB。

因此这个脚本做的是「派生 + 校验」，不是简单压缩：

- 主文件用 ``skill/redskill/SKILL.md``（市场专版）
- ``skill/redskill/references/`` 原样带上
- ``skill/campusnet/references/`` 里平台无关的三份排障文档复用过来
- ``skill/campusnet/scripts/`` 的两个脚本一起打进去（白名单允许 .py）
- ``LICENSE`` → ``LICENSE.txt``（原扩展名会被拒）

用法::

    python skill/build_redskill.py                  # 输出到 skill/dist/
    python skill/build_redskill.py --out 某目录      # 指定输出目录
"""

import argparse
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

RED_SRC = os.path.join(HERE, "redskill")
FULL_REFS = os.path.join(HERE, "campusnet", "references")
FULL_SCRIPTS = os.path.join(HERE, "campusnet", "scripts")

#: 平台的文件白名单。实测报错原文就是这 5 种。
ALLOWED_EXT = {".md", ".py", ".js", ".json", ".txt"}

#: 复用过来的三份排障文档（平台无关，两版共用）
REUSED_REFS = ("troubleshooting.md", "platforms.md", "fingerprinting.md")

#: 一起打进去的脚本（白名单允许 .py，所以直接从通用版复用，不另存一份）
BUNDLED_SCRIPTS = ("run.py", "fingerprint.py")

#: SKILL.md 的字符上限（平台硬限制）
MAX_SKILL_MD_CHARS = 10000

MAX_FILE = 10 * 1024 * 1024
MAX_TOTAL = 30 * 1024 * 1024

#: 正文里提到 ``scripts/xxx`` 时，这个文件必须真的在包里 ——
#: 白名单允许 .py 之后，风险从"提到了不存在的脚本"变成了"脚本没打进去"。
_SCRIPT_REF = re.compile(r"scripts/([A-Za-z0-9_][A-Za-z0-9_.-]*)")
#: 形如 `python3 xxx.py` 的命令行调用，用来核对被调用的文件是否存在
_CMD_INVOKE = re.compile(r"^\s*(?:python3?|sh|bash|node)\s+([A-Za-z0-9_./-]+\.(?:py|js|sh))",
                         re.MULTILINE)


def _read_lf(path):
    """读成文本并把行尾统一成 LF。"""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    return text.replace("\r\n", "\n").replace("\r", "\n")


def collect():
    """返回 {归档内路径: 内容}，路径分隔符统一用 /。"""
    files = {}

    skill_md = os.path.join(RED_SRC, "SKILL.md")
    if not os.path.isfile(skill_md):
        raise SystemExit("缺少 {}".format(skill_md))
    files["SKILL.md"] = _read_lf(skill_md)

    red_refs = os.path.join(RED_SRC, "references")
    for name in sorted(os.listdir(red_refs)):
        path = os.path.join(red_refs, name)
        if os.path.isfile(path):
            files["references/{}".format(name)] = _read_lf(path)

    for name in REUSED_REFS:
        path = os.path.join(FULL_REFS, name)
        if not os.path.isfile(path):
            raise SystemExit("缺少复用的文档 {}".format(path))
        files["references/{}".format(name)] = _read_lf(path)

    for name in BUNDLED_SCRIPTS:
        path = os.path.join(FULL_SCRIPTS, name)
        if not os.path.isfile(path):
            raise SystemExit("缺少脚本 {}".format(path))
        files["scripts/{}".format(name)] = _read_lf(path)

    license_src = os.path.join(REPO, "LICENSE")
    if os.path.isfile(license_src):
        # 扩展名 `.LICENSE` 那种形态会被拒，所以补一个 .txt
        files["LICENSE.txt"] = _read_lf(license_src)

    return files


def validate(files):
    """把平台的硬性要求前置成断言 —— 宁可在本地炸，也别传上去被拒。"""
    problems = []

    root_md = files.get("SKILL.md", "")
    if not root_md:
        problems.append("根目录没有 SKILL.md")
    else:
        count = len(root_md)
        if count > MAX_SKILL_MD_CHARS:
            problems.append(
                "SKILL.md {} 字符，超过平台上限 {}（把细节拆到 references/ 子文件，"
                "主文件只留导航）".format(count, MAX_SKILL_MD_CHARS)
            )
        if not root_md.startswith("---\n"):
            problems.append("SKILL.md 没有 YAML frontmatter（平台要靠它读 name/description）")
    if any(key.startswith("campusnet/") for key in files):
        problems.append("出现了同名文件夹层级（平台要求 SKILL.md 在根目录）")

    for key, text in files.items():
        ext = os.path.splitext(key)[1].lower()
        if ext not in ALLOWED_EXT:
            problems.append(
                "{}：扩展名 {} 不在白名单 {} 里，会被平台拒".format(
                    key, ext, " ".join(sorted(ALLOWED_EXT))
                )
            )
        if "\r\n" in text:
            problems.append("{}：行尾不是 LF（CRLF 会让 frontmatter 解析失败）".format(key))
        if "\ufeff" in text:
            problems.append("{}：带了 BOM".format(key))
        if len(text.encode("utf-8")) > MAX_FILE:
            problems.append("{}：超过单文件 10MB".format(key))

        # 正文里提到 / 调用的脚本必须真的在包里
        for match in _SCRIPT_REF.findall(text):
            if "scripts/{}".format(match) not in files:
                problems.append("{}：提到了不存在的 scripts/{}".format(key, match))
        for match in _CMD_INVOKE.findall(text):
            base = os.path.basename(match)
            if base in ("run.py", "fingerprint.py") and "scripts/{}".format(base) not in files:
                problems.append("{}：让人执行 {}，但包里没有它".format(key, match))

    total = sum(len(t.encode("utf-8")) for t in files.values())
    if total > MAX_TOTAL:
        problems.append("总大小 {} 字节，超过 30MB".format(total))

    return problems, total


def build(out_dir):
    files = collect()
    problems, total = validate(files)

    print("待打包文件：")
    for key in sorted(files):
        text = files[key]
        print("  {:<40} {:>7} 字节 {:>7} 字符".format(
            key, len(text.encode("utf-8")), len(text)))
    print("  {:<40} {:>7} 字节".format("（合计）", total))

    if problems:
        print("\n校验未通过：")
        for item in problems:
            print("  ✘ {}".format(item))
        raise SystemExit(1)
    print("\n✔ 校验通过：根目录 SKILL.md / 字符数达标 / 扩展名在白名单 / 行尾 LF / 体积达标")

    os.makedirs(out_dir, exist_ok=True)
    zip_path = os.path.join(out_dir, "campusnet-redskill.zip")

    # SKILL.md 写成**归档里的第一条**：平台"认根目录那个文件"，
    # 很多实现是顺着 namelist 找第一个 .md，把主文件放最前面最稳。
    order = ["SKILL.md"] + sorted(k for k in files if k != "SKILL.md")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for key in order:
            zf.writestr(key, files[key])

    size = os.path.getsize(zip_path)
    print("✔ 已生成 {}（{} 字节）".format(zip_path, size))

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
    print("\n解压后的结构（SKILL.md 必须在最外层）：")
    for name in names:
        print("  {}".format(name))

    # 校验的是**"在根目录"**，不是"排第一"：只要 SKILL.md 不带目录前缀即可。
    assert "SKILL.md" in names, "归档里没有 SKILL.md"
    assert "/" not in [n for n in names if n == "SKILL.md"][0], "SKILL.md 带了目录前缀"
    assert not any(n.startswith("./") for n in names), "条目带了 ./ 前缀"
    assert names[0] == "SKILL.md", "SKILL.md 应该是归档第一条"
    return zip_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="打包给开源技能市场用的 skill")
    parser.add_argument("--out", default=os.path.join(HERE, "dist"))
    args = parser.parse_args(argv)
    build(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
