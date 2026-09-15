# community/ —— 社区贡献的适配层

这个目录放的是**官方代码之外的适配方案**：同样是解决校园网自动登录，
但针对的是主程序照顾不到的特殊场景。它们不受主程序的版本节奏约束，
可以更激进、更贴合特定硬件。

## openwrt/

给 OpenWrt 路由器的方案。

| 文件 | 说明 |
| --- | --- |
| [`campusnet-openwrt.sh`](campusnet-openwrt.sh) | **纯 busybox sh 版**，零依赖，只用 `uclient-fetch`。给装不上 Python 的机器用。 |

### 什么时候用这个，什么时候用主程序

| 情况 | 用什么 |
| --- | --- |
| 路由器 flash 够（≥ 16 MB），能 `opkg install python3-light` | 用**主程序**：`campusnet autostart install`，功能完整 |
| flash 很小 / 不想装 Python / 只有 8 MB 的老机器 | 用这个 **shell 版** |
| 想用 Srun / 锐捷 / eportal | 必须用**主程序**（shell 版只实现了 Dr.COM） |

路由器上主程序的完整指引（含「最近突然失效了」的排查清单）见
[`docs/openwrt.md`](../../docs/openwrt.md)。

### shell 版快速开始

```sh
scp campusnet-openwrt.sh root@192.168.1.1:/usr/bin/
ssh root@192.168.1.1
chmod +x /usr/bin/campusnet-openwrt.sh

# 配置（标准 UCI 格式）
cat > /etc/config/campusnet <<'EOF'
config campusnet 'main'
	option enabled '1'
	option username '你的学号'
	option password '你的密码'
	option portal '10.99.0.1'
	option r1 '0'
	option r3 '0'
	option para '00'
	option suffix ''
EOF

# 手动验证
/usr/bin/campusnet-openwrt.sh -v

# 装进 cron
echo '*/5 * * * * /usr/bin/campusnet-openwrt.sh >/dev/null 2>&1' >> /etc/crontabs/root
/etc/init.d/cron enable && /etc/init.d/cron restart
```

### 参数对照（Dr.COM）

`r1` / `r3` / `para` / `suffix` 的含义和主程序一致，
照抄主程序 [README 的运营商表](../../README.md#登录前要先选运营商) 即可：

| 学校页面上的选项 | `r1` | `r3` | `para` | `suffix` |
| --- | --- | --- | --- | --- |
| 校园用户 | 0 | 0 | `00` | （空） |
| 校园电信 | 1 | 0 | `00` | （空） |
| 校园联通 | 0 | 1 | `00` | （空） |
| 校园其他 | 0 | 0 | `30` | （空） |
| 移动 | 0 | 0 | `30` | `@cmcc` |
| 电信 | 0 | 0 | `00` | `@telecom` |
| 联通 | 0 | 0 | `00` | `@unicom` |

### 运行测试

```sh
sh tests/test_shell.sh
```

覆盖配置解析和 URL 编码 —— URL 编码那块踩过 busybox 的转义陷阱，
所以专门钉了回归测试。
