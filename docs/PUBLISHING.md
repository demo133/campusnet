# 发布整理清单

这份清单把"代码写完了"到"GitHub 上能搜到"之间的事一次性列清楚。

> **当前状态：下面这套流程已经走完了，仓库发布在 https://github.com/demo133/campusnet **
> 保留完整流程备查，将来发新版本或别人 fork 时仍可按此操作。

**按顺序做，大约 5 分钟。**

---

## 一、替换占位符（必做）

仓库里有 4 个文件带 `github.com/<you>/campusnet` 占位符：

| 文件 | 位置 |
| --- | --- |
| `README.md` | 安装章节的两个地址 |
| `pyproject.toml` | `Homepage` / `Issues` |
| `CHANGELOG.md` | 底部的版本对比链接 |
| `docs/releases/v0.1.0.md` | Issues 链接 |

把下面的 `你的用户名` 换成你的 GitHub 用户名，在仓库根目录执行一次即可：

```bash
python -c "import pathlib,sys;u=sys.argv[1];[p.write_text(p.read_text(encoding='utf-8').replace('<you>',u),encoding='utf-8') for p in map(pathlib.Path,['README.md','pyproject.toml','CHANGELOG.md','docs/releases/v0.1.0.md'])]" 你的用户名
```

改完确认一下没有漏网的（`PUBLISHING.md` 自己提到占位符，要排除）：

```bash
grep -rn "<you>" . --exclude-dir=.git --exclude=PUBLISHING.md
```

> 输出为空才算干净。

---

## 二、设置提交身份

首个 commit 用的是中性身份 `campusnet <campusnet@users.noreply.github.com>`。
想换成你自己：

```bash
git commit --amend --reset-author
```

（需要先配好 `git config user.name` / `user.email`）

---

## 三、本地自检

```bash
python -m pytest -q                     # 43 passed 才算正常
python -m campusnet --version           # campusnet 0.1.0
python -m campusnet providers           # 应列出 5 个 provider
git status                              # 工作树必须是干净的
```

再确认一遍**没有把密码或本机信息提交上去**：

```bash
git ls-files | grep -i -E "config.json|cred|password|secret"
```

> 输出为空才安全。

---

## 四、建远程仓库并推送

在 GitHub 上新建一个 **空仓库**（不要勾选 README / .gitignore / License），然后：

```bash
git remote add origin https://github.com/你的用户名/campusnet.git
git push -u origin main
```

---

## 五、打 tag 并发布 Release

```bash
git tag -a v0.1.0 -m "campusnet v0.1.0 · 首个公开版本"
git push origin v0.1.0
```

然后在 GitHub 上：**Releases → Draft a new release**

| 字段 | 填什么 |
| --- | --- |
| Choose a tag | 选 `v0.1.0` |
| Release title | `campusnet v0.1.0 · 校园网自动登录` |
| Describe this release | 把 `docs/releases/v0.1.0.md` **全文**粘进去（含二级标题，GitHub 会自动渲染） |
| Attach binaries | 不用传，这是纯 Python 项目 |

勾上 **Set as the latest release**，发布。

---

## 六、发布后检查

- [ ] 仓库首页的 README 渲染正常，徽章不是坏图
- [ ] Release 页面排版正常（标题、表格、代码块都对）
- [ ] Actions 里的 CI 跑绿了（矩阵是 3 系统 × 3 个 Python 版本）
- [ ] Issues 页面能看到「上报学校指纹」这个模板
- [ ] 用无痕窗口打开 `https://github.com/你的用户名/campusnet`，确认没暴露本地路径

---

## 七、发布之后

**别急着到处宣传。** `srun` / `ruijie` / `eportal` 三条路径没有真机验证，
现在推广大概率会收到"我这边报错"的 issue。

建议节奏：

1. 先发到学校论坛 / 班级群 —— 同校同学可以直接用，因为 `drcom` 实测过了
2. 再到 V2EX、少数派等地方发帖，请不同学校的同学跑 `campusnet detect` 反馈指纹
3. 收到 3 所以上不同学校的验证反馈后，再发 v0.2.0 正式推广

**下一步最该做的事**，是攒一个「已实测学校」列表放进 README：

| 学校 | 认证系统 | 验证人 |
| --- | --- | --- |
| *(待补充)* | Dr.COM 城市热点 | 首个版本 |

每多一行，项目可信度就高一截——这比多支持三个厂商更有用。

---

## 附：文件清单

```
campusnet/
├── README.md                   项目门面（中文）
├── CHANGELOG.md                版本日志
├── LICENSE                     MIT
├── pyproject.toml              打包配置 + 入口点
├── .gitignore  .gitattributes
├── .github/
│   ├── workflows/ci.yml        3 OS × 3 Python 矩阵测试
│   └── ISSUE_TEMPLATE/fingerprint.md
├── docs/
│   ├── providers.md            Provider 开发指南（含三种协议完整报文）
│   ├── openwrt.md              路由器部署与排查手册
│   ├── skill.md                skill 的结构 / 安装 / 打包
│   ├── PUBLISHING.md           本文件
│   └── releases/v0.1.0.md      Release 说明（粘到 GitHub 用）
├── campusnet/
│   ├── cli.py                  命令行入口
│   ├── config.py               配置与凭据
│   ├── session.py              HTTP 层（标准库）
│   ├── detector.py             联网判定 + 指纹识别
│   ├── runner.py               探测 → 尝试 → 校验
│   ├── autostart.py            三平台开机自启
│   └── providers/              drcom / srun / ruijie / eportal / custom
├── skill/                      skill 包（通用版 + 市场专版）
└── tests/                      252 个用例 + Dr.COM 门户页面样本
```
