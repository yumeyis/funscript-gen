#!/usr/bin/env bash
# 安裝並設定 funscript-gen 的執行環境。可重複執行：已完成的步驟會略過。
#
# 用法：
#   ./set-env.sh          互動模式（缺少 uv 時詢問是否安裝、詢問 AI API 設定）
#   ./set-env.sh -y       非互動模式（自動安裝 uv；.env 不存在時只複製範本，不詢問）
#   ./set-env.sh --test   安裝完成後執行單元測試
#   ./set-env.sh --pose   另外安裝骨架模式（--mode pose）需要的 PyTorch 與 YOLO（約 0.8 GB）並下載權重
#   ./set-env.sh --pose-cuda  同上，但用 CUDA 版 PyTorch（NVIDIA 顯示卡，約 2.5 GB；之後的 uv sync 也要加 --extra pose-cuda）
#
# 會做的事：
#   1. 確認系統工具（uv）
#   2. 用 uv 安裝 Python 3.12 與套件（依 uv.lock，版本固定；--pose 時加上選配的 pose）
#   3. 有 --pose 時預先下載 YOLO 骨架模型權重
#   4. 建立 .env（AI API 設定；之後也可以在 Web UI 的「設定」分頁修改）
#   5. 測試 AI API 連線（有設定時）
set -euo pipefail

cd "$(dirname "$0")"

ASSUME_YES=0
RUN_TESTS=0
WITH_POSE=0
POSE_EXTRA=pose
for arg in "$@"; do
    case "$arg" in
        -y|--yes) ASSUME_YES=1 ;;
        --test) RUN_TESTS=1 ;;
        --pose) WITH_POSE=1 ;;
        --pose-cuda) WITH_POSE=1; POSE_EXTRA=pose-cuda ;;
        -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "未知的參數：$arg（用 --help 查看說明）" >&2; exit 2 ;;
    esac
done

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m ✓\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m !\033[0m %s\n' "$*"; }
fail()  { printf '\033[1;31m ✗\033[0m %s\n' "$*" >&2; exit 1; }

ask() {  # ask "問題" -> 0 表示是
    [ "$ASSUME_YES" = 1 ] && return 0
    local reply
    read -r -p "$1 [y/N] " reply
    [[ "$reply" =~ ^[Yy]$ ]]
}

# --- 1. 系統工具 -------------------------------------------------------------
info "檢查系統工具"
[ "$(uname -s)" = "Linux" ] || warn "目前只在 Linux 上測試過（偵測到 $(uname -s)）"

if ! command -v uv >/dev/null 2>&1 && [ -x "$HOME/.local/bin/uv" ]; then
    export PATH="$HOME/.local/bin:$PATH"
fi
if ! command -v uv >/dev/null 2>&1; then
    warn "找不到 uv（Python 套件與版本管理工具）"
    if ask "要從 https://astral.sh/uv 下載並安裝 uv 嗎？"; then
        command -v curl >/dev/null 2>&1 || fail "需要 curl 才能安裝 uv"
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$PATH"
        command -v uv >/dev/null 2>&1 || fail "uv 安裝後仍找不到，請重新開啟終端機後再執行一次"
    else
        fail "需要 uv，請參考 https://docs.astral.sh/uv/ 安裝後再執行"
    fi
fi
ok "uv $(uv --version | awk '{print $2}')"


# --- 2. Python 與套件 --------------------------------------------------------
if [ "$WITH_POSE" = 1 ]; then
    info "安裝 Python 與套件，含骨架模式（第一次約需幾分鐘，會下載 $([ "$POSE_EXTRA" = pose-cuda ] && echo CUDA || echo CPU) 版 PyTorch）"
    uv sync --frozen --python 3.12 --extra "$POSE_EXTRA"
else
    info "安裝 Python 與套件（第一次約需幾分鐘）"
    uv sync --frozen --python 3.12
fi
ok "套件安裝完成（$(uv run --frozen python --version)）"

# --- 3. 模型權重 -------------------------------------------------------------
if [ "$WITH_POSE" = 1 ]; then
    info "下載 YOLO 骨架模型權重"
    if [ -f yolo11n-pose.pt ]; then
        ok "yolo11n-pose.pt 已存在"
    else
        uv run --frozen python -c "from ultralytics import YOLO; YOLO('yolo11n-pose.pt')" >/dev/null
        ok "yolo11n-pose.pt 下載完成"
    fi
else
    ok "略過骨架模式（--mode pose，需要時執行 ./set-env.sh --pose）"
fi

# --- 4. .env -----------------------------------------------------------------
info "設定 AI API（.env）"
if [ -f .env ]; then
    ok ".env 已存在，不修改（可在 Web UI 的「設定」分頁調整）"
else
    cp .env.example .env
    chmod 600 .env
    if [ "$ASSUME_YES" = 0 ]; then
        echo "請輸入 AI 服務的連線資訊，直接按 Enter 使用括號中的預設值："
        read -r -p "  後端：openai（vLLM、LM Studio 等 OpenAI 相容服務）或 ollama [openai]: " backend
        if [ "$backend" = ollama ]; then def_url=http://127.0.0.1:11434; def_model=qwen3-vl:8b-instruct
        else backend=; def_url=http://127.0.0.1:8000/v1; def_model=Qwen/Qwen3-VL-8B-Instruct; fi
        read -r -p "  端點網址 [$def_url]: " url
        read -r -s -p "  API 金鑰（輸入時不會顯示，可留空）: " key; echo
        read -r -p "  模型 [$def_model]: " model
        uv run --frozen python - "$backend" "${url:-$def_url}" "$key" "${model:-$def_model}" <<'PY'
import sys
from funscript_gen.config import Settings, save_env
backend, url, key, model = sys.argv[1:5]
s = Settings()
s = s.model_copy(update={k: v for k, v in {"vllm_backend": backend, "vllm_base_url": url, "vllm_api_key": key,
                                           "vllm_model": model}.items() if v})
save_env(s)
PY
        ok ".env 已建立（權限 600）"
    else
        ok "已從 .env.example 建立 .env（尚未填入連線資訊，請編輯 .env 或使用 Web UI 的「設定」分頁）"
    fi
fi

# --- 5. 連線測試 -------------------------------------------------------------
info "測試 AI API 連線"
if uv run --frozen python - <<'PY'
import sys
from funscript_gen.config import Settings, list_models
s = Settings()
try:
    models = list_models(s)
except Exception as e:  # noqa: BLE001
    print(f"   無法連線 {s.vllm_base_url}：{e}")
    sys.exit(1)
mark = "" if s.vllm_model in models else f"（注意：設定的模型 {s.vllm_model} 不在清單中）"
print(f"   {s.vllm_base_url} 可用的模型：{', '.join(models)}{mark}")
PY
then
    ok "AI API 連線正常"
else
    warn "AI API 目前無法連線；不影響安裝，可以之後再設定（不使用 AI 時可在 Web UI 關閉）"
fi

# --- 6. 測試（選用） ---------------------------------------------------------
if [ "$RUN_TESTS" = 1 ]; then
    info "執行單元測試"
    uv run --frozen pytest -q
fi

echo
ok "環境設定完成。啟動 Web UI：./start-webui.sh"
