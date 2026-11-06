#!/bin/sh
# Container entrypoint: creates /data/.env on the first start, then runs funscript-gen.
#   (no arguments) / webui   start the web UI on 0.0.0.0:7860
#   <any other subcommand>   e.g. `generate /videos/a.mp4`, passed to funscript-gen as is
set -e

if ! [ -w . ]; then
    echo "/data is not writable by uid $(id -u): create the folder first (mkdir -p data videos) or set UID/GID" >&2
    exit 1
fi

# .env is created once from the template, filled in from INIT_VLLM_* (docker-compose.ollama.yaml points it at the
# ollama service). After that the web UI's 設定 tab (or editing /data/.env) is the place to change it: VLLM_* set in
# the container's environment would override .env and make the tab's 儲存設定 look like it did nothing.
if [ ! -f .env ]; then
    cp /app/.env.example .env
    python - <<'PY'
import os
from funscript_gen.config import Settings, save_env
update = {f: os.environ[f"INIT_{f.upper()}"] for f in ("vllm_backend", "vllm_base_url", "vllm_api_key", "vllm_model")
          if os.environ.get(f"INIT_{f.upper()}")}
save_env(Settings().model_copy(update=update))
PY
    echo "created /data/.env (AI settings: edit it or use the web UI's 設定 tab)"
fi

if [ $# -eq 0 ] || [ "$1" = webui ]; then
    [ $# -gt 0 ] && shift
    exec funscript-gen webui --host 0.0.0.0 --port 7860 "$@"
fi
exec funscript-gen "$@"
