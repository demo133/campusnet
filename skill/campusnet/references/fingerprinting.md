# 给一所新学校加支持

这个项目最需要的是**不同学校的真实指纹**，而不是更多功能。
给一所新学校加支持，多数情况就是加一条识别特征，或者填几个 `--option`。

---

## 一、先拿到指纹

```sh
python3 -m campusnet detect --verbose
```

`--verbose` 会打印每个 HTTP 请求的细节。输出里关注四样东西：

| 关注点 | 为什么重要 |
| --- | --- |
| **认证系统** | 决定走哪个 provider（`drcom` / `srun` / `ruijie` / `eportal`） |
| **门户地址** | `portal_ip`，写进配置 |
| **页面标题** | 最可靠的识别特征之一（如「上网登录页」） |
| **页面里的参数名与取值** | 如 `authuserfield=DDDDD`、`R1=`、`para=` |

探测失败时，加 `--portal` 直接指定地址，跳过自动探测：

```sh
python3 -m campusnet detect --portal 10.99.0.1 --verbose
```

---

## 二、各家的识别特征

| 认证系统 | 典型特征 |
| --- | --- |
| **drcom**（Dr.COM 城市热点） | 响应头 `Server: DrcomServer1.0`；页面 `Dr.COMWebLoginID_0.htm`；标题「上网登录页」；参数 `DDDDD` / `upass` / `0MKKey` / `R1` / `R3` / `para` |
| **srun**（深澜） | URL 出现 `/srun_portal_pc`、`/cgi-bin/rad_user_info`；参数 `ac_id` / `nas_ip` / `challenge`；登录前先要过 `get_challenge` |
| **ruijie**（锐捷） | 跳转到锐捷 AC 的 `service` 参数页；需要先取一次 `query_string` |
| **eportal**（通用 / 华为 AC） | URL `/eportal/?c=ACSetting&a=Login`；无参数访问会返回 `Msg=01 无法获取用户认证账号` |

> ⚠️ **`srun` / `ruijie` / `eportal` 三条路径没有真机验证**，只有 `drcom` 实测过。
> 用户用这三家失败时，如实说明这一点，并请他提供 `detect --verbose` 的输出。

---

## 三、各 provider 可用的参数

用 `--option k=v` 直接写（可重复），或写进配置文件的 `options` 里：

```sh
python3 -m campusnet once --provider drcom --option r1=1 --option para=00
```

| Provider | 参数 |
| --- | --- |
| `drcom` | `carrier`、`r1`、`r3`、`para`、`username_suffix`、`0MKKey` |
| `srun` | `carrier` → `domain`、`ac_id`、`n`、`type`、`os` |
| `ruijie` | `service`、`query_string` |
| `eportal` | `r1`、`r3`、`para`、`0MKKey` |
| `custom` | `url`、`method`、`body`、`headers`、`success_regex`、`failure_regex`、`ac_id` |

**不要把 `r1` / `para` 之类的值猜出来填。** 这些只能来自：
1. `detect` 从登录页 JS 里解析出来的值；
2. 用户在浏览器 F12 → Network 里抓到的真实请求。

猜出来的参数会编出一套看起来合理、但完全不工作的配置。

---

## 四、识别不出来时：用 `custom` 模板

学校改版、给接口加密（登录页 JS 里出现 `page_data_encrypt=1`，
接口变成 `/eportal/portal/*`）时，预置 provider 可能匹配不上。
这时用 `custom` 自己拼。

**先在浏览器里抓一条真实的成功请求**（F12 → Network → 登录一次 → 找到那个请求），
记下：URL、方法、表单字段、响应里表示成功的字样。

然后写配置：

```json
{
  "username": "学号",
  "provider": "custom",
  "portal_ip": "10.0.0.1",
  "options": {
    "url": "http://10.0.0.1/eportal/portal/login?user={user}&pass={password}&ac_id={ac_id}",
    "method": "POST",
    "body": "user={user}&pass={password}",
    "headers": { "Referer": "http://10.0.0.1/" },
    "success_regex": "\"result\"\\s*:\\s*1",
    "ac_id": "1"
  }
}
```

`{user}` / `{password}` / `{ac_id}` 是占位符，登录时会被替换。

先单独验证一次：

```sh
python3 -m campusnet once --provider custom --verbose
```

---

## 五、反馈格式（最有价值的三样）

生成一份**自动脱敏**的报告 —— 用本 skill 附带的脱敏脚本
（源码见 `references/helper-scripts.md`；
如果装的是带脚本的那一版，直接用 `scripts/fingerprint.py`）：

```sh
python3 fingerprint.py
```

它会跑一次探测，并自动打码账号、IP、MAC、密码，输出可以直接粘贴的文本。

再补上两样：

```sh
python3 -m campusnet doctor                    # 体检输出
cat /etc/openwrt_release                        # 路由器用户：型号 + 版本
```

三样一起贴到 issue（模板见 `.github/ISSUE_TEMPLATE/fingerprint.md`）。

**打码务必自己再检查一遍。** 自动脱敏覆盖常见形态，但不能保证零遗漏。

**协议常量不要打码**：`0MKKey=123456`、`ac_id=1`、`para=00` 是协议固定值，
不是个人信息，打码了报告反而没法看。

---

## 六、加进代码里要改什么

拿到指纹后，加支持的位置：

| 改动 | 文件 |
| --- | --- |
| 识别特征（抓哪些关键词、怎么打分） | `campusnet/providers/__init__.py` 的 `fingerprint()` |
| 认证参数怎么拼 | `campusnet/providers/<厂商>.py` |
| 测试 | `tests/test_<厂商>.py`，参考 `tests/test_drcom.py` 用真实页面样本 |

页面样本放在 `tests/fixtures/`（已有一个 `drcom_login_page.html` 可参照）。
**先写测试再改代码** —— 指纹规则全是正则，没有测试兜着很容易改坏别的学校。
