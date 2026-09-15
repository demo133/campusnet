#!/bin/sh
# campusnet-openwrt.sh —— 校园网 Portal 自动登录（纯 busybox sh 版，零依赖）
#
# 给装不上 Python 的路由器用。只依赖 OpenWrt 自带的 uclient-fetch。
#
# 用法：
#   /usr/bin/campusnet-openwrt.sh              # 跑一次（cron 用这个）
#   /usr/bin/campusnet-openwrt.sh -v           # 带详细输出
#   /usr/bin/campusnet-openwrt.sh -c /path/cfg # 指定配置文件
#
# cron 条目（写在 /etc/crontabs/root）：
#   */5 * * * * /usr/bin/campusnet-openwrt.sh >/dev/null 2>&1
#
# 退出码：0 = 已在线或登录成功；1 = 登录失败（cron 会因此给你发信）
#
# 设计上刻意保持"安静"：已联网时一个字都不打印。
# 路由器上每 5 分钟一条日志，很快就会把 logread 刷满。

set -u

CONFIG="/etc/config/campusnet"
VERBOSE=0
TIMEOUT=8
# 联网探测点：(URL, 期望内容关键字, 期望状态码)
# 用 uclient-fetch 拿不到状态码时退回看内容，所以这里是"或"的关系。
PROBE_URL="http://connect.rom.miui.com/generate_204"
PROBE_FALLBACK="http://www.baidu.com"

# ------------------------------------------------------------------ 工具函数
log() {
	# $VERBOSE 可能还没赋值（函数被单独 source 测试时），所以用 :- 兜底
	[ "${VERBOSE:-0}" = "1" ] || return 0
	echo "[campusnet] $*" >&2
}

err() {
	# 错误永远要打印 —— 哪怕在静默模式。不然 cron 里出了问题你完全看不到。
	echo "[campusnet] ERROR: $*" >&2
}

have() {
	command -v "$1" >/dev/null 2>&1
}

# uclient-fetch 是 OpenWrt 自带的；curl / wget 作为兜底
http_get() {
	# $1 = URL；stdout 为响应体；失败时非零
	if have uclient-fetch; then
		uclient-fetch -q -O - -T "$TIMEOUT" "$1" 2>/dev/null
	elif have curl; then
		curl -fsS --max-time "$TIMEOUT" "$1" 2>/dev/null
	elif have wget; then
		wget -q -O - -T "$TIMEOUT" "$1" 2>/dev/null
	else
		err "找不到 uclient-fetch / curl / wget，无法发请求"
		return 127
	fi
}

_utils_oct3() {
	# 十进制字节 -> 三位八进制（如 65 -> "101"）。
	#
	# 补足三位：printf 的 ``\ooo`` 转义最多吃三位八进制，补齐最不容易出歧义。
	oct=$(printf '%o' "$1")
	case ${#oct} in
		1) printf '00%s' "$oct" ;;
		2) printf '0%s' "$oct" ;;
		*) printf '%s' "$oct" ;;
	esac
}

_byte_to_char() {
	# 十进制字节 -> 该字节本身（用于 unreserved 字符的原样输出）。
	#
	# "怎么把整数变回字符"是这类脚本最绕的地方。这里的办法是：
	# 把 ``\ooo`` 放在 printf 的**格式串**位置 —— 格式串不会再被 shell
	# 解析一遍，所以不会出现"反斜杠被吃一层"（见 urlencode 的注释）。
	printf "$(printf '\\%s' "$(_utils_oct3 "$1")")"
}

_byte_to_pct() {
	# 十进制字节 -> %XX。输出纯 ASCII，任何 printf 实现都能编。
	printf '%%%02X' "$1"
}

urlencode() {
	# URL 编码（RFC 3986）。**逐字节**处理，所以中文密码也编得对。
	#
	# 踩过的三个坑留在这里，省得下次又"顺手简化"回去：
	#
	#   1. ``printf '\xNN'`` —— busybox 的 ash **不支持** \x 转义。
	#   2. ``printf '%b' "\\$oct"`` —— %b 只认**八进制**，而且反斜杠一旦
	#      放进变量再展开就会被吃掉一层，最终输出字面量 ``$o``。
	#      实测过 6 种写法全都是这个结果。
	#   3. **在 awk 里用 ``sprintf("%c", code)`` 反查字符来造 ord()** ——
	#      macOS 自带的是 BSD awk（既不是 gawk 也不是 busybox awk），
	#      它的 ``%c`` 只对 0..255 里的一部分值给出单字节，其余吐空串，
	#      于是整张反查表全部命中兜底值，**任何**输入都编成一串 %3F。
	#      同一份脚本在 Linux（mawk / busybox awk）上完全正常 ——
	#      这就是那个"只在 macOS CI 上挂"的 bug。
	#
	# 做法：**先把字节读成十进制整数，再按整数算**。
	# 链路上没有任何一步依赖"字符长得像什么"，所以不在乎是哪个实现。
	#
	#   - ``od -An -v -tu1``  一次拿到全部字节的十进制值
	#   - ``tr -s``           把 od 的换行/空格折成空格，正好当分隔符
	#   - 算术比较            判定 A-Z / a-z / 0-9 / - . _ ~
	#
	# 两个参数不能省：
	#   - ``-v``    od 默认把连续重复行折叠成 ``*``，长串会丢字节
	#   - LC_ALL=C  否则 od 按 locale 的"字符"而不是"字节"切
	#
	# 用法：urlencode "字符串"
	_enc_out=""
	for _enc_d in $(printf '%s' "$1" | LC_ALL=C od -An -v -tu1 | tr -s ' \t\n' ' '); do
		# RFC 3986 unreserved: A-Z(65-90) a-z(97-122) 0-9(48-57) - . _ ~(45 46 95 126)
		if { [ "$_enc_d" -ge 65 ] && [ "$_enc_d" -le 90 ]; } \
			|| { [ "$_enc_d" -ge 97 ] && [ "$_enc_d" -le 122 ]; } \
			|| { [ "$_enc_d" -ge 48 ] && [ "$_enc_d" -le 57 ]; } \
			|| [ "$_enc_d" -eq 45 ] || [ "$_enc_d" -eq 46 ] \
			|| [ "$_enc_d" -eq 95 ] || [ "$_enc_d" -eq 126 ]; then
			_enc_out="${_enc_out}$(_byte_to_char "$_enc_d")"
		else
			_enc_out="${_enc_out}$(_byte_to_pct "$_enc_d")"
		fi
	done
	printf '%s' "$_enc_out"
}

# ------------------------------------------------------------------ 读配置
load_config() {
	[ -f "$CONFIG" ] || { err "配置文件不存在：$CONFIG"; return 1; }

	# 直接 source UCI 格式（它就是 shell 变量赋值，能 source）
	# 但 UCI 的 'config campusnet main' 这类行会让 sh 报错，所以先过滤
	#
	# ⚠ 这条正则**只能用 POSIX BRE**，一个扩展都不能用：
	#   BSD sed（macOS 上的那个）在默认模式下把 ``\+`` / ``\?`` / ``\|``
	#   当**字面字符**，而不是量词 —— 于是 ``[[:space:]]\+`` 变成"匹配
	#   一个空白后面跟一个加号"，整条规则**一条都匹配不到**，
	#   ``eval`` 拿到空串，表现成"配置文件读不出任何东西"。
	#   而 GNU sed 会把它当量词，所以在 Linux / OpenWrt(busybox) 上完全正常。
	#   ⇒ 用 ``\{1,\}`` 代替 ``\+``（POSIX 区间表达式，两边都认）。
	eval "$(sed -n "s/^[[:space:]]*option[[:space:]]\{1,\}\([A-Za-z_][A-Za-z0-9_]*\)[[:space:]]\{1,\}'\{0,1\}\([^']*\)'\{0,1\}[[:space:]]*$/\1='\2'/p" "$CONFIG")"

	ENABLED="${enabled:-1}"
	USERNAME="${username:-}"
	PASSWORD="${password:-}"
	PORTAL="${portal:-}"
	R1="${r1:-0}"
	R3="${r3:-0}"
	PARA="${para:-00}"
	SUFFIX="${suffix:-}"
	PROVIDER="${provider:-drcom}"

	if [ "$ENABLED" = "0" ]; then
		log "配置里 enabled=0，跳过"
		return 2
	fi
	[ -n "$USERNAME" ] || { err "配置里没有 username"; return 1; }
	[ -n "$PASSWORD" ] || { err "配置里没有 password（cron 环境里没有 shell 变量，必须写进配置）"; return 1; }
	[ -n "$PORTAL" ] || { err "配置里没有 portal（认证门户地址）"; return 1; }
	return 0
}

# ------------------------------------------------------------------ 联网判定
is_online() {
	# generate_204 能正常返回空内容就算通了。
	# 门户会把它劫持成 200 + 登录页 HTML，所以不能只看"请求成功"。
	body=$(http_get "$PROBE_URL") || return 1
	if [ -n "$body" ]; then
		# 有内容说明被劫持了（真实 204 应该是空的）
		return 1
	fi
	# 再抓一个真实网页确认 —— 有些学校把探测地址加白名单，
	# 只看上面那条会误判成"已联网"
	body2=$(http_get "$PROBE_FALLBACK") || return 1
	case "$body2" in
		*baidu*) return 0 ;;
		*) return 1 ;;
	esac
}

# ------------------------------------------------------------------ 登录
# Dr.COM JSONP 接口。返回 0 = 成功
drcom_login() {
	user="${USERNAME}${SUFFIX}"
	enc_user=$(urlencode "$user")
	enc_pass=$(urlencode "$PASSWORD")
	ts=$(date +%s)
	cb="dr1003"

	url="http://${PORTAL}/drcom/login?callback=${cb}"
	url="${url}&DDDDD=${enc_user}&upass=${enc_pass}&0MKKey=123456"
	url="${url}&R1=${R1}&R2=&R3=${R3}&R6=0&para=${PARA}&v6ip=&v=${ts}"

	log "GET ${url%%\?*}?..."

	resp=$(http_get "$url") || { err "请求失败（门户 ${PORTAL} 不通？）"; return 1; }

	case "$resp" in
		*'"result":1'*|*'"result": 1'*)
			log "认证成功"
			return 0
			;;
		*'"result":2'*|*'"result": 2'*|*'"result":3'*|*'"result": 3'*)
			log "已在线上"
			return 0
			;;
		*'"result":'*)
			msg=$(echo "$resp" | sed -n "s/.*\"msga\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p")
			err "认证失败：${msg:-$resp}"
			return 1
			;;
	esac

	err "响应无法识别：$(printf '%.200s' "$resp")"
	return 1
}

# ------------------------------------------------------------------ 主流程
while [ $# -gt 0 ]; do
	case "$1" in
		-v|--verbose) VERBOSE=1 ;;
		-c|--config) shift; CONFIG="${1:-$CONFIG}" ;;
		-h|--help)
			sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
			exit 0
			;;
		*) err "未知参数：$1"; exit 2 ;;
	esac
	shift
done

load_config || exit $?

if is_online; then
	log "已联网，无需认证"
	# 已联网时**静默**退出 —— cron 日志空间很珍贵，正常情况不该留痕迹
	exit 0
fi

log "检测到网络未认证，开始登录…"

case "$PROVIDER" in
	drcom) drcom_login ;;
	*)
		err "纯 shell 版只支持 drcom，provider=${PROVIDER} 请改用 Python 版"
		exit 1
		;;
esac
rc=$?

if [ "$rc" -eq 0 ]; then
	# 接口说成功还不够，等两秒再确认真的通了
	sleep 2
	if is_online; then
		log "网络已连通"
		exit 0
	fi
	err "接口返回成功，但联网校验没通过"
	exit 1
fi

exit "$rc"
