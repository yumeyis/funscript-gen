#!/usr/bin/env bash
# 啟動 funscript-gen 的 Web UI 伺服器。
#
# 用法：
#   ./start-webui.sh
#
# 伺服器設定在下方「設定」區塊。每一項都可以用同名的環境變數覆寫，例如：
#   WEBUI_PORT=7861 ./start-webui.sh
# 只屬於這台電腦、不想提交到 git 的設定，可以寫在 start-webui.local.sh（已列在 .gitignore，啟動時會自動載入）。
#
# AI API（端點、金鑰、模型）也不在這裡設定：請在 .env 或 Web UI 的「設定」分頁修改。
set -euo pipefail

cd "$(dirname "$0")"

# 本機設定（選用，不提交）。優先順序：環境變數 > start-webui.local.sh > 下方預設值
SETTINGS=(WEBUI_HOST WEBUI_PORT WEBUI_OUTPUT_DIR)
declare -A FROM_ENV=()
for v in "${SETTINGS[@]}"; do
    [ -n "${!v+x}" ] && FROM_ENV[$v]="${!v}"
done
if [ -f start-webui.local.sh ]; then
    # shellcheck source=/dev/null
    source start-webui.local.sh
fi
for v in "${!FROM_ENV[@]}"; do
    printf -v "$v" '%s' "${FROM_ENV[$v]}"
done

# ============================== 設定 ==============================
# 監聽位址：127.0.0.1 只允許本機連線；0.0.0.0 允許區網其他電腦連線
# Web UI 設計給單人使用，沒有登入：開放區網時，能連到這台電腦的人都能使用，並能修改 AI 端點與金鑰
WEBUI_HOST="${WEBUI_HOST:-127.0.0.1}"
# 連接埠
WEBUI_PORT="${WEBUI_PORT:-7860}"
# 產生的 funscript 存放位置
WEBUI_OUTPUT_DIR="${WEBUI_OUTPUT_DIR:-out/webui}"
# ==================================================================

warn() { printf '\033[1;33m !\033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m ✗\033[0m %s\n' "$*" >&2; exit 1; }

if ! command -v uv >/dev/null 2>&1 && [ -x "$HOME/.local/bin/uv" ]; then
    export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || fail "找不到 uv，請先執行 ./set-env.sh"
[ -d .venv ] || fail "尚未安裝環境，請先執行 ./set-env.sh"

[[ "$WEBUI_PORT" =~ ^[0-9]+$ ]] && [ "$WEBUI_PORT" -ge 1 ] && [ "$WEBUI_PORT" -le 65535 ] \
    || fail "WEBUI_PORT 必須是 1–65535 的數字（目前：$WEBUI_PORT）"

# 連接埠被占用時，指出是哪個程式
if command -v ss >/dev/null 2>&1 && ss -ltn "sport = :$WEBUI_PORT" | grep -q LISTEN; then
    who=$(ss -ltnp "sport = :$WEBUI_PORT" 2>/dev/null | grep -o 'users:(([^)]*' | head -1 | sed 's/users:((//')
    fail "連接埠 $WEBUI_PORT 已被占用${who:+（$who）}；請關閉該程式，或用 WEBUI_PORT=其他埠號 ./start-webui.sh"
fi

if [ "$WEBUI_HOST" != "127.0.0.1" ] && [ "$WEBUI_HOST" != "localhost" ]; then
    warn "Web UI 開放在 $WEBUI_HOST 且沒有登入：能連到這台電腦的人都能使用，並能修改 AI 端點與金鑰"
fi

[ -f .env ] || warn "找不到 .env：AI API 尚未設定，可在 Web UI 的「設定」分頁填寫"

if [ "$WEBUI_HOST" = "0.0.0.0" ]; then
    addr=$(hostname -I 2>/dev/null | awk '{print $1}')
    echo "Web UI：http://${addr:-<這台電腦的 IP>}:$WEBUI_PORT（本機：http://127.0.0.1:$WEBUI_PORT）"
else
    echo "Web UI：http://$WEBUI_HOST:$WEBUI_PORT"
fi
echo "按 Ctrl+C 停止伺服器"

exec uv run --frozen funscript-gen webui --host "$WEBUI_HOST" --port "$WEBUI_PORT" \
    --output-dir "$WEBUI_OUTPUT_DIR"
