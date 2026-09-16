# 认证系统与 Provider 开发指南

## 已支持的认证系统

| Provider | 识别特征 | 登录接口 | 验证情况 |
| --- | --- | --- | --- |
| `drcom` | 响应头 `Server: DrcomServer1.0`；页面含 `Dr.COMWebLoginID_0.htm`、`v4serip`、`DDDDD`/`upass` | `GET /drcom/login`（JSONP）+ `POST :801/eportal/?c=ACSetting&a=Login` | ✅ 真实环境实测 |
| `srun` | 页面/URL 含 `srun_portal`、`cgi-bin/get_challenge`；`ac_id` | `GET /cgi-bin/get_challenge` → `GET /cgi-bin/srun_portal` | 已实现，待更多学校验证 |
| `ruijie` | 页面含 `InterFace.do`、`queryString` | `POST /eportal/InterFace.do?method=login` | 已实现，待更多学校验证 |
| `eportal` | 页面含 `c=ACSetting&a=Login`、`wlanuserip` | `POST /eportal/?c=ACSetting&a=Login` | 已实现，待更多学校验证 |
| `eportal_portal` | URL 含 `eportal/portal/login`、`dr1003`、`jsVersion` | `GET /eportal/portal/login`（JSONP `dr1003`） | 已实现，待更多学校验证 |
| `custom` | 不参与识别，必须显式指定 | 模板拼接，见 README | ✅ |

## 三种协议的细节

### Dr.COM（城市热点）

国内高校占有率很高，且**同一台服务器通常同时暴露新旧两套接口** —— 这是它很好支持的原因。

**传统 JSONP 接口**（推荐，最干净）：

```
GET http://<portal>/drcom/login?callback=dr1003
    &DDDDD=<账号>&upass=<密码>
    &0MKKey=123456&R1=0&R2=&R3=0&R6=0&para=00&v6ip=&v=<unix 时间戳>

→ dr1003({"result":1,"msg":1,"uid":"<账号>","msga":"", ...})
```

`result == 1` 是成功；`msga` 里带人类可读的失败原因（如 `userid error1`）。
字段名很反人类（`DDDDD` 是账号，`upass` 是密码），但这就是它的历史约定。

登录页上的「服务类型」四个选项通过 `R1` / `R3` / `para` 区分，
详见 `campusnet/providers/drcom.py` 里的 `CARRIERS` 表。

**经典 ACSetting 接口**（801 / 803 端口）：

```
POST http://<portal>:801/eportal/?c=ACSetting&a=Login&wlanuserip=...&mac=...
body: DDDDD=<账号>&upass=<密码>&R1=0&R3=0&para=00&0MKKey=123456
→ <script>Msg=00;time=0;msga=''</script>      # Msg=00 成功，其余为失败
```

### 深澜 Srun

三步走，带一次性 challenge 和自研编码：

```
1. GET  /cgi-bin/get_challenge?callback=jsonp&username=<账号>&ip=<本机IP>
   → jsonp({"challenge":"...","client_ip":"..."})

2. hmd5   = md5(password + challenge)
   info   = "{SRBX1}" + srun_base64( info_json XOR challenge )
   chksum = sha1(challenge + username + hmd5 + challenge + acid + challenge
                 + ip + challenge + n + challenge + type + challenge + info)

3. GET  /cgi-bin/srun_portal?action=login&username=<账号>
        &password={MD5}<hmd5>&ac_id=<ac_id>&ip=<本机IP>
        &chksum=<chksum>&info=<urlencoded info>&n=200&type=1&os=Windows&name=Windows
   → jsonp({"error":"ok", ...})
```

两个坑：

1. `srun_base64` **不是标准 base64**。它用一套置换过的字母表
   （`LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA`），
   直接 `base64.b64encode` 出来的结果服务器不认。
2. `password` 字段不能直接传密码，得是 `{MD5}` 前缀 + 上面算出的 `hmd5`。

`ac_id` 各校不同，绝大多数是 `1`；不确定就跑 `campusnet detect`，它会从页面里抠出来。

### 锐捷 Ruijie

```
POST http://<portal>/eportal/InterFace.do?method=login
body: userId=<账号>&password=<密码>&service=<服务名>
      &queryString=<门户URL里的那一串>&operatorPwd=&operatorUserId=
      &validcode=&passwordEncrypt=false
→ {"result":"success","message":"..."}
```

`queryString` 是页面 URL 里带的 `wlanuserip=...&wlanacname=...&nasip=...`，
通常从门户页面的 JS 变量里抠。抠不到时会退化拼一个，多数学校也能过。

### 新版 eportal（portal/login JSONP）

较新的 eportal 部署把认证挪到了一条 **GET** 查询串接口上，
老接口（`ACSetting` / `InterFace.do`）在这类门户上不存在：

```
GET http://<portal>:801/eportal/portal/login?callback=dr1003
    &login_method=1&user_account=<账号>&user_password=<密码>
    &wlan_user_ip=<本机IP>&wlan_user_ipv6=&wlan_user_mac=000000000000
    &wlan_ac_ip=&wlan_ac_name=&jsVersion=4.2.1&terminal_type=1
    &lang=zh-cn&v=5911

→ dr1003({"result":1,"msg":"认证成功","valid":1})
```

* `result == 1` 成功；`msg` 带人类可读的失败原因，也用它识别「已在线」
* **运营商就是账号后缀**：`@cmcc` / `@unicom` / `@telecom`，校园网不带后缀，
  由 `carrier` 选项自动翻译
* 识别靠 URL 里的 `portal/login` + `dr1003` + `jsVersion` —— 这些参数在
  网关 302 的 `Location` 里就带着，所以探测阶段会把重定向地址补进指纹上下文

## 新增一个 Provider

1. 在 `campusnet/providers/` 下新建 `yourvendor.py`：

```python
from .base import DetectContext, LoginResult, Provider
from ..session import local_ip

class YourVendorProvider(Provider):
    name = "yourvendor"
    display_name = "厂商中文名"
    min_confidence = 0.4

    @classmethod
    def detect(cls, ctx: DetectContext) -> float:
        score = 0.0
        if "某个独特字符串" in ctx.lower_text:
            score += 0.7
        return min(score, 1.0)

    def login(self, portal, username, password, client_ip="", mac=""):
        ip = client_ip or local_ip()
        for origin in self.origins(portal):
            resp = self.session.post(origin + "/login", data={...}, headers={...})
            if "success" in resp.text.lower():
                return LoginResult(True, self.name, "认证成功", endpoint=origin)
        return LoginResult(False, self.name, "登录失败")
```

2. 在 `campusnet/providers/__init__.py` 的 `PROVIDERS` 里注册；
3. 在 `tests/` 下加一个测试，**重点是断言请求参数拼对了**（用 `conftest.FakeSession` 抓请求）；
4. 在 `tests/fixtures/` 放一份脱敏后的门户页面 HTML，加一条指纹测试；
5. 更新本文档和 README 的表格。

## 提交指纹样本

不知道自家学校是什么系统？跑：

```bash
campusnet detect --verbose
```

把输出贴到 issue 里即可。**注意先把账号、IP、MAC 打码**。

## Windows 上改用计划任务（可选）

默认的开机自启走注册表 `Run` 项 + `campusnet watch` 常驻守护，
好处是不需要管理员权限、且"网络变化"这种事件触发用轮询也能覆盖。

如果你更想要计划任务（比如希望"连上 Wi-Fi 的瞬间"就触发，而不是等下一个轮询周期），
可以自己建一个，动作填：

```
powershell.exe -NoProfile -WindowStyle Hidden -Command "pythonw -m campusnet watch --interval 10"
```

触发条件建议同时勾选：

- 用户登录时
- 事件：`Microsoft-Windows-NetworkProfile/Operational`，事件 ID `10000`
- 每 10 分钟重复一次
