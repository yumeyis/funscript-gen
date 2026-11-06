"""Settings loaded from the environment / .env (AI backend credentials live here, never in code)."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from funscript_gen.paths import settings_file

ENV_FILE = settings_file(".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    vllm_backend: str = "openai"  # "openai" (any OpenAI-compatible server) or "ollama" (Ollama's native API)
    vllm_base_url: str = "http://127.0.0.1:8000/v1"
    vllm_api_key: str = ""
    vllm_model: str = "Qwen/Qwen3-VL-8B-Instruct"
    vllm_bbox_format: str = ""  # "rel1000" or "abs"; empty = guess from the model name
    vllm_image_max_side: int = 768
    vllm_timeout_s: float = 120.0
    # Requests sent at the same time; vLLM batches them (A04, 16 scenes, no cached answers: 4 -> AI step 64 s,
    # 8 -> 29 s, 16 -> 15 s).
    vllm_concurrency: int = 8
    # Ollama only: context length per request. Ollama gives Qwen3-VL about 1040 tokens per image and the region pick
    # sends up to 8 images (8429 tokens on A04); Ollama's own default (4096 on an 8 GB GPU) rejects even 4. The KV
    # cache grows with it (about 2.3 GB at 16384 for Qwen3-VL 4B or 8B).
    vllm_num_ctx: int = 16384


ENV_KEYS = {  # Settings field -> .env variable written by save_env()
    "vllm_backend": "VLLM_BACKEND",
    "vllm_base_url": "VLLM_BASE_URL",
    "vllm_api_key": "VLLM_API_KEY",
    "vllm_model": "VLLM_MODEL",
    "vllm_bbox_format": "VLLM_BBOX_FORMAT",
    "vllm_concurrency": "VLLM_CONCURRENCY",
    "vllm_num_ctx": "VLLM_NUM_CTX",
}

BACKENDS = ("openai", "ollama")


def save_env(settings: Settings, path: str | Path = ENV_FILE) -> None:
    """Write the AI settings into .env, keeping every other line (comments, unrelated variables)."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending = {var: str(getattr(settings, field)) for field, var in ENV_KEYS.items()}
    out = []
    for line in lines:
        m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m and m.group(1) in pending:
            out.append(f"{m.group(1)}={pending.pop(m.group(1))}")
        else:
            out.append(line)
    out += [f"{var}={value}" for var, value in pending.items()]
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    path.chmod(0o600)  # holds the API key


def list_models(settings: Settings) -> list[str]:
    return make_provider(settings, use_cache=False).list_models()


def make_provider(settings: Settings | None = None, use_cache: bool = True):
    from funscript_gen.ai.cache import ResponseCache
    from funscript_gen.ai.ollama import OllamaProvider
    from funscript_gen.ai.openai_compat import OpenAICompatProvider

    s = settings or Settings()
    if s.vllm_backend not in BACKENDS:
        raise ValueError(f"unknown AI backend {s.vllm_backend!r} (VLLM_BACKEND: {', '.join(BACKENDS)})")
    if s.vllm_backend == "ollama":
        return OllamaProvider(
            s.vllm_base_url,
            s.vllm_api_key,
            s.vllm_model,
            num_ctx=s.vllm_num_ctx,
            image_max_side=s.vllm_image_max_side,
            # Ollama computes one request at a time by default and queues the rest, so a request may first wait for
            # every other one in flight (16 queued 8-image requests took over 120 s).
            timeout_s=s.vllm_timeout_s * max(1, s.vllm_concurrency),
            cache=ResponseCache(enabled=use_cache),
        )
    return OpenAICompatProvider(
        s.vllm_base_url,
        s.vllm_api_key,
        s.vllm_model,
        image_max_side=s.vllm_image_max_side,
        timeout_s=s.vllm_timeout_s,
        cache=ResponseCache(enabled=use_cache),
    )
