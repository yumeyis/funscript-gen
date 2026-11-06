import sys

from funscript_gen.config import Settings, save_env


def test_save_env_updates_keys_and_keeps_other_lines(tmp_path, monkeypatch):
    for var in ("VLLM_BACKEND", "VLLM_BASE_URL", "VLLM_API_KEY", "VLLM_MODEL", "VLLM_BBOX_FORMAT", "VLLM_CONCURRENCY",
                "VLLM_NUM_CTX"):
        monkeypatch.delenv(var, raising=False)
    env = tmp_path / ".env"
    env.write_text("# comment\nVLLM_BASE_URL=http://old/v1\nOTHER=keep\nVLLM_API_KEY=secret\n")
    save_env(Settings(_env_file=None, vllm_base_url="http://new/v1", vllm_api_key="secret",
                      vllm_model="m", vllm_bbox_format="abs", vllm_concurrency=16, vllm_backend="ollama",
                      vllm_num_ctx=16384), env)
    text = env.read_text()
    assert text.startswith("# comment\nVLLM_BASE_URL=http://new/v1\nOTHER=keep\nVLLM_API_KEY=secret\n")
    assert "VLLM_MODEL=m\n" in text and "VLLM_BBOX_FORMAT=abs\n" in text
    if sys.platform != "win32":  # Windows has no POSIX permission bits
        assert env.stat().st_mode & 0o077 == 0  # not readable by others
    loaded = Settings(_env_file=env)
    assert (loaded.vllm_base_url, loaded.vllm_model, loaded.vllm_bbox_format) == ("http://new/v1", "m", "abs")
    assert loaded.vllm_concurrency == 16 and "VLLM_CONCURRENCY=16\n" in text
    assert (loaded.vllm_backend, loaded.vllm_num_ctx) == ("ollama", 16384)


def test_ai_workers_follow_the_settings_unless_set():
    from funscript_gen.pipeline import PipelineOptions, _ai_workers

    s = Settings(_env_file=None, vllm_concurrency=12)
    assert _ai_workers(PipelineOptions(ai_settings=s)) == 12
    assert _ai_workers(PipelineOptions(ai_settings=s, ai_workers=3)) == 3


def test_backend_picks_the_provider():
    import pytest

    from funscript_gen.ai.ollama import OllamaProvider
    from funscript_gen.ai.openai_compat import OpenAICompatProvider
    from funscript_gen.config import make_provider

    assert type(make_provider(Settings(_env_file=None), use_cache=False)) is OpenAICompatProvider
    p = make_provider(Settings(_env_file=None, vllm_backend="ollama", vllm_base_url="http://h:11434/v1",
                               vllm_num_ctx=16384), use_cache=False)
    assert isinstance(p, OllamaProvider) and p.num_ctx == 16384 and str(p.client.base_url) == "http://h:11434"
    assert p.client.timeout.read == 120 * 8  # queued behind the other requests in flight
    with pytest.raises(ValueError, match="VLLM_BACKEND"):
        make_provider(Settings(_env_file=None, vllm_backend="olama"))
