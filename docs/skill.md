# 把 campusnet 包装成 skill

这份文档说明 skill 长什么样、怎么装、怎么打包分发。

---

## 一、先明确 skill 解决的是哪个问题

**不是"怎么装"——是"装完坏了怎么自己修"。**

装 campusnet 本来就一条 `pip install`，做成 skill 没什么增量。
真正的痛点在另一端：用户跑通了、用了两个月，某天突然失效，
然后他不知道从哪查起 —— 门户地址变了？运营商变了？cron 被关了？
密码在 cron 环境里取不到？

所以这个 skill 的主体不是安装步骤，而是**判断场景 → 选对命令 → 按症状定位**。
这也决定了它的形态：知识（references）比代码（scripts）更重要。

---

## 二、skill 的结构

```
skill/campusnet/
├── SKILL.md                        触发词 + 工作流（探测→配置→登录→自启→排障）
├── references/
│   ├── troubleshooting.md          按【症状】查的排障表（七类路由故障 + 桌面端）
│   ├── platforms.md                各平台路径/自启位置/日志/命令支持矩阵
│   └── fingerprinting.md           给一所新学校加支持
└── scripts/
    ├── run.py                      定位可用的 campusnet（已装 / 本机源码）并调用
    └── fingerprint.py              采集【自动脱敏】的指纹报告
```

三个设计决定值得说明：

**1. `scripts/run.py` 存在的理由。**
skill 被调用时，用户机器可能是三种状态：装了包、只有一个源码目录、什么都没有。
让调用方每次去猜 `python` 还是 `python3`、要不要拼 `PYTHONPATH`，既啰嗦又容易错。
收敛成一个脚本，`run.py` 找不到时会直接打印安装命令。

**2. `fingerprint.py` 是战略性的，不是附属品。**
项目里 `srun` / `ruijie` / `eportal` 三条路径**没有真机验证**。
想变可信只能靠不同学校的真实指纹。与其在 issue 模板里写"记得打码"，
不如把打码做成脚本 —— 自动打码比提醒有效。

**3. 排障文档按症状组织，不按原因组织。**
用户说的是"突然不行了"，不是"我怀疑 portal_ip 变了"。
`references/troubleshooting.md` 的索引表就是从症状查起的。

---

## 三、怎么装

### 方式 A：仓库里直接用（开发者）

skill 就在仓库里，`run.py` 会自动往上找到源码目录，不需要额外安装：

```sh
python skill/campusnet/scripts/run.py --version
```

### 方式 B：装成用户级 skill（普通用户）

把 `skill/campusnet/` 整个复制到你所用的技能目录里。
目录位置各家产品不同，常见的约定是用户主目录下的 `skills/`：

```sh
git clone https://github.com/demo133/campusnet.git
cp -r campusnet/skill/campusnet <技能目录>/skills/
pip install git+https://github.com/demo133/campusnet.git
```

`pip install` 这一步不能省 —— 装进技能目录之后，
脚本已经不在仓库里了，只能靠已安装的包。

### 方式 C：从压缩包装

```sh
# 拿到 campusnet.zip 后，解压到技能目录
unzip campusnet.zip -d <技能目录>/skills/
```

压缩包由 `package_skill.py` 生成（见下节）。

---

## 四、怎么打包

用 skill-creator 的打包脚本，它会**先校验再打包**：

```sh
python <skill-creator>/scripts/package_skill.py skill/campusnet skill/dist
```

成功输出：

```text
🔍 Validating skill...
✅ Skill is valid!
✅ Successfully packaged skill to: skill/dist/campusnet.zip
```

**改完 skill 一定要重新跑一遍打包**，否则压缩包会停在旧版本。
`skill/dist/` 不进版本库（见 `.gitignore`），它是构建产物。

---

## 五、维护注意

**唯一的真源是仓库里的 `skill/campusnet/`。**

用户级安装（技能目录下的 `campusnet/`）和压缩包都是**副本**，
改了仓库里的不会自动同步。改完按这个顺序走一遍：

1. 改 `skill/campusnet/` 下的文件
2. `python skill/campusnet/scripts/run.py --version` —— 确认脚本还能跑
3. `package_skill.py` 重新打包
4. 重新 `cp -r` 到技能目录

### 已知的边界

- skill 自身**不含** campusnet 源码。装 skill 不等于装工具，
  还得 `pip install`。这是刻意的取舍 —— 把源码复制进 skill 会立刻产生分叉。
- `scripts/fingerprint.py` 的脱敏覆盖常见形态（IPv4 / MAC / 密码字段 / 长数字），
  **不保证零遗漏**，报告里要保留"请自行再检查一遍"的提示。
- 排障知识主要来自 Dr.COM 的实测和 OpenWrt 的通用规律。
  另外三家厂商的排障细节，等收到真实案例再补。
