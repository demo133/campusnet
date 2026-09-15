#!/bin/sh
# 测试 campusnet-openwrt.sh 的配置解析与 URL 编码（不需要真实网络）
#
# 跑法：sh tests/test_shell.sh
# CI 上三个平台都会跑 —— **不能只跑 Linux**。
# 这个文件里已经栽过两次"只在 macOS 上挂"：
#   1. urlencode 曾用 awk 的 sprintf("%c") 反查字符，BSD awk 不认；
#   2. 读配置的 sed 曾用 `\+`，BSD sed 在默认 BRE 模式下把它当**字面加号**，
#      于是整条规则一条都匹配不到（GNU sed 当量词，所以 Linux/OpenWrt 全绿）。
# 两次都是"Linux 绿、macOS 红"，而且都只有日志才知道具体栽在哪。

set -u

SCRIPT="${SCRIPT:-community/openwrt/campusnet-openwrt.sh}"
FAILED=0

pass() { echo "  PASS  $1"; }

annotate() {
	# $1 = error | warning      $2 = 消息
	#
	# 把一条消息发成 GitHub Actions 的 **check-run annotation**。
	#
	# 为什么要多此一举：这个仓库的 job 日志**匿名读不到**（API 返回 403），
	# 而 `::error::` 工作流命令会被收集成 annotation，
	# annotation 能通过公开 API 拿到：
	#   GET /repos/<o>/<r>/check-runs/<id>/annotations
	# 于是"只在某个平台上挂"的时候，不需要登录也能看到**到底哪条断言红了**。
	# 之前吃过亏：只知道 macOS 挂了，不知道挂在配置解析还是 URL 编码，
	# 只能靠猜 —— 结果同一个文件里其实有两个独立的 macOS 专属问题。
	#
	# 两个格式要求，违反了整条消息会被截断（踩过）：
	#   1. 必须是**单行** —— 所以把换行压成空格；
	#   2. `%` 必须转义成 `%25` —— 否则像 `%3F`、`%E4%B8%AD` 这种
	#      本来就在消息里的百分号会被解析成转义序列。
	[ -n "${GITHUB_ACTIONS:-}" ] || return 0
	_msg=$(printf '%s' "$2" | tr '\n' ' ' | sed 's/%/%25/g')
	echo "::$1 title=shell test::$_msg" >&2
}

fail() {
	echo "  FAIL  $1"
	annotate error "$1"
	FAILED=$((FAILED + 1))
}

bail() {
	# 提前退出（脚本结构被人改坏之类）也要留下 annotation，
	# 否则同样只剩"步骤红了"这一个信息。
	echo "$1"
	annotate error "$1"
	exit 1
}

check_eq() {
	# $1=说明 $2=期望 $3=实际
	if [ "$2" = "$3" ]; then
		pass "$1"
	else
		fail "$1（期望 [$2]，实际 [$3]）"
	fi
}

# ---------------------------------------------------------------- 准备夹具
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# 把脚本里的函数抠出来单独测（脚本主体会去发网络请求，不能直接跑）
extract_function() {
	# $1 = 函数名。从 "name() {" 一直取到**列 0 的 "}"** ——
	# 用 awk 的大括号计数不行，因为函数体里有 awk 的 { } 字符串。
	awk -v fn="$1" '
		$0 ~ "^" fn "\\(\\) \\{" { inside = 1 }
		inside { print }
		inside && /^\}/ { exit }
	' "$SCRIPT"
}

FUNCS="$TMP/funcs.sh"
{
	echo 'set -u'
	extract_function log
	extract_function err
	extract_function have
	extract_function http_get
	extract_function _utils_oct3
	extract_function _byte_to_char
	extract_function _byte_to_pct
	extract_function urlencode
	extract_function load_config
} > "$FUNCS"

if [ ! -s "$FUNCS" ]; then
	bail "无法从 $SCRIPT 提取函数，脚本结构可能变了"
fi

# 提取是否完整：urlencode 依赖 od + 三个小工具函数，缺一个就编不出来
#
# 用 `grep -F`（定长字符串）而不是正则：裸 `{` 在 BRE 里是未定义行为 ——
# GNU grep 把 `\{` 当区间表达式的开始，看到孤立的 `\{` 直接报 "Unmatched \{"；
# BSD grep 则把裸 `{` 当字面字符。两边都不写正则最省事。
if ! grep -q 'od -An -v -tu1' "$FUNCS"; then
	bail "urlencode 提取不完整（少了 od 那一段）"
fi
if ! grep -q -F '_byte_to_char() {' "$FUNCS" || ! grep -q -F '_byte_to_pct() {' "$FUNCS"; then
	bail "urlencode 的辅助函数没提取全"
fi

# ---------------------------------------------------------------- 可移植性静态检查
# 守住"只在 macOS 上挂"这一类问题，而且是**静态**发现，不用等 CI 红。
#
# BSD sed（macOS 自带）在默认 BRE 模式下把 \+ \? \| 当**字面字符**。
# 也就是说写 `a\+` 的人以为在说"一个或多个 a"，BSD sed 看到的是"a 后面跟一个加号"——
# 表达式本身不报错，只是**永远匹配不到**。这类静默失效最难查。
# 三个扩展在 POSIX BRE 里的等价值：\+ → \{1,\}   \? → \{0,1\}   \| → 无（BRE 没有或）
#
# 只查含 sed 的**代码**行（去掉 -n 的行号前缀后以 # 开头的是注释）。
# 注释里为了说明问题必然会写出这些字符，不能误报。
_bad=$(grep -n 'sed[[:space:]]' "$SCRIPT" \
	| grep -v '^[0-9][0-9]*:[[:space:]]*#' \
	| grep -F -e '\+' -e '\?' -e '\|' || true)
if [ -n "$_bad" ]; then
	bail "脚本里的 sed 用了 GNU 扩展（BSD sed 会静默匹配不到）：
$_bad"
fi
pass "sed 只用了 POSIX BRE（没有 \+ \? \|）"

# ---------------------------------------------------------------- 配置解析
echo "配置解析："

cat > "$TMP/campusnet" <<'EOF'
config campusnet 'main'
	option enabled '1'
	option username '2200000000'
	option password 'p@ss word&x'
	option portal '10.99.0.1'
	option r1 '0'
	option r3 '0'
	option para '00'
	option suffix '@cmcc'
EOF

OUT=$(CONFIG="$TMP/campusnet" sh -c ". '$FUNCS'; load_config; echo \"rc=\$?\"; echo \"user=\$USERNAME\"; echo \"pass=\$PASSWORD\"; echo \"portal=\$PORTAL\"; echo \"suffix=\$SUFFIX\"; echo \"para=\$PARA\"" 2>&1)

case "$OUT" in
	*"rc=0"*)              pass "配置文件能被解析（rc=0）" ;;
	*)                     fail "配置文件解析失败：$OUT" ;;
esac
case "$OUT" in
	*"user=2200000000"*)   pass "username 读取正确" ;;
	*)                     fail "username 读错了：$OUT" ;;
esac
case "$OUT" in
	*"pass=p@ss word&x"*)  pass "密码里的空格和 & 没被截断（引号处理正确）" ;;
	*)                     fail "密码读错了：$OUT" ;;
esac
case "$OUT" in
	*"portal=10.99.0.1"*) pass "portal 读取正确" ;;
	*)                     fail "portal 读错了：$OUT" ;;
esac
case "$OUT" in
	*"suffix=@cmcc"*)      pass "suffix 读取正确" ;;
	*)                     fail "suffix 读错了：$OUT" ;;
esac
case "$OUT" in
	*"para=00"*)           pass "para=00 保持字符串（没变成 0）" ;;
	*)                     fail "para 读错了：$OUT" ;;
esac

# 缺 key 时必须失败，且不能崩
echo "配置校验："

printf "config campusnet 'main'\n\toption username 'x'\n" > "$TMP/missing"
OUT=$(CONFIG="$TMP/missing" sh -c ". '$FUNCS'; load_config; echo \"rc=\$?\"" 2>&1)
case "$OUT" in
	*"rc=1"*)  pass "缺 password/portal 时返回 rc=1" ;;
	*)         fail "缺 key 时没有正确报错：$OUT" ;;
esac

printf "config campusnet 'main'\n\toption enabled '0'\n\toption username 'x'\n" > "$TMP/disabled"
OUT=$(CONFIG="$TMP/disabled" sh -c ". '$FUNCS'; load_config; echo \"rc=\$?\"" 2>&1)
case "$OUT" in
	*"rc=2"*)  pass "enabled=0 时返回 rc=2（跳过而不是失败）" ;;
	*)         fail "enabled=0 没被识别：$OUT" ;;
esac

OUT=$(CONFIG="$TMP/does-not-exist" sh -c ". '$FUNCS'; load_config; echo \"rc=\$?\"" 2>&1)
case "$OUT" in
	*"rc=1"*)  pass "配置文件不存在时返回 rc=1" ;;
	*)         fail "配置文件不存在时行为不对：$OUT" ;;
esac

# ---------------------------------------------------------------- URL 编码
echo "URL 编码："

enc() {
	sh -c ". '$TMP/funcs.sh'; urlencode \"\$1\"" _ "$1"
}

check_eq "学号 @ 后缀，@ 被编码" "%40" "$(enc '@')"
check_eq "空格被编码成 %20" "%20" "$(enc ' ')"
check_eq "& 被编码" "%26" "$(enc '&')"
check_eq "字母数字保持不变" "abc123" "$(enc 'abc123')"
check_eq "连字符保持不变" "a-b" "$(enc 'a-b')"
check_eq "下划线保持不变" "a_b" "$(enc 'a_b')"
check_eq "点保持不变" "a.b" "$(enc 'a.b')"

# 综合：学号加 @cmcc 后缀
check_eq "2200000000@cmcc 编码正确" "2200000000%40cmcc" "$(enc '2200000000@cmcc')"
# 密码含特殊字符
check_eq "p@ss word&x 编码正确" "p%40ss%20word%26x" "$(enc 'p@ss word&x')"

# ---------------------------------------------------------------- 中文（回归）
# 这一组是**防回归的重点**。最初的实现用 awk 的 sprintf("%c", n) 反查字符
# 来造 ord()，在 Linux 上没问题，但 macOS 自带的 BSD awk 返回的不是单字节，
# 于是整张表全部命中兜底值 —— 任何输入都变成一串 %3F。
# CI 上表现为「Linux 全绿、macOS 全红」，而日志里只看到一条断言失败。
echo "中文 URL 编码（跨平台回归）："

# UTF-8 逐字节编码：一个汉字 3 个字节，所以是 3 组 %XX
check_eq "单个汉字「中」编码为 UTF-8" "%E4%B8%AD" "$(enc '中')"
check_eq "「密码」编码为 UTF-8" "%E5%AF%86%E7%A0%81" "$(enc '密码')"
check_eq "「校园网」编码正确" \
	"%E6%A0%A1%E5%9B%AD%E7%BD%91" "$(enc '校园网')"
# 中文 + 特殊字符混合
check_eq "中文密码 中#123 编码正确" \
	"%E4%B8%AD%23123" "$(enc '中#123')"
# 关键断言：**不能**出现 %3F（那是字符反查失败的产物）
_out=$(enc '中文密码')
case "$_out" in
	*'%3F'*) fail "中文被编成了 %3F（说明又踩了 awk %c 的坑）：$_out" ;;
	*)       pass "中文没有退化成 %3F" ;;
esac

# ---------------------------------------------------------------- 汇总
echo
if [ "$FAILED" -eq 0 ]; then
	echo "全部通过"
	exit 0
fi
echo "$FAILED 项失败"
# 告警也发一条 annotation：这样"某平台红了"在 API 上能直接看到失败条数，
# 不用登录去翻日志。
annotate warning "$FAILED 项断言失败"
exit 1
