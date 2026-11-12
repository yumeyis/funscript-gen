from types import SimpleNamespace

import numpy as np
import pytest

from funscript_gen.ai.base import InvalidResponse, LabeledImage
from funscript_gen.ai.cache import ResponseCache
from funscript_gen.ai.openai_compat import OpenAICompatProvider
from funscript_gen.ai.prompts import BBox, SceneAnalysis, bbox_to_unit, default_bbox_format

VALID = (
    '{"people_count":2,"has_interaction":true,"motion":"rhythmic","subjects":['
    '{"description":"left","bbox":{"x1":100,"y1":200,"x2":400,"y2":900}},'
    '{"description":"right","bbox":{"x1":500,"y1":200,"x2":800,"y2":900}}],'
    '"focus_roi":null,"motion_axis":"vertical","ref_a":"hip","ref_b":"hip","confidence":0.8}'
)


def test_bbox_formats():
    assert bbox_to_unit(BBox(x1=250, y1=0, x2=750, y2=1000), "rel1000", 1920, 1080) == (0.25, 0.0, 0.75, 1.0)
    assert bbox_to_unit(BBox(x1=960, y1=540, x2=480, y2=1200), "abs", 1920, 1080) == (0.25, 0.5, 0.5, 1.0)
    assert default_bbox_format("Qwen/Qwen2.5-VL-7B-Instruct") == "abs"
    assert default_bbox_format("Qwen/Qwen3-VL-8B-Instruct") == "rel1000"


class _FakeCompletions:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        text = self.replies.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def _provider(tmp_path, replies):
    p = OpenAICompatProvider("http://x/v1", "k", "m", cache=ResponseCache(tmp_path), retries=1)
    fake = _FakeCompletions(replies)
    p.client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    return p, fake


def _images():
    return [LabeledImage(np.zeros((64, 64, 3), np.uint8), "Frame 1:")]


def test_parses_fenced_json_and_caches(tmp_path):
    p, fake = _provider(tmp_path, [f"```json\n{VALID}\n```"])
    r1 = p.analyze(_images(), "prompt", SceneAnalysis)
    r2 = p.analyze(_images(), "prompt", SceneAnalysis)
    assert r1 == r2 and r1.ref_a == "hip" and fake.calls == 1


def test_refusal_raises_invalid_response(tmp_path):
    p, fake = _provider(tmp_path, ["I can't help with that.", "I can't help with that."])
    with pytest.raises(InvalidResponse) as e:
        p.analyze(_images(), "prompt", SceneAnalysis)
    assert "can't" in e.value.raw and fake.calls == 2


def test_retry_after_bad_output(tmp_path):
    p, fake = _provider(tmp_path, ['{"people_count": 2', VALID])
    assert p.analyze(_images(), "prompt", SceneAnalysis).motion == "rhythmic"
    assert fake.calls == 2


def _ollama(tmp_path, handler, **kw):
    import httpx

    from funscript_gen.ai.ollama import OllamaProvider

    p = OllamaProvider("http://h:11434/v1", "", "qwen3-vl:8b", cache=ResponseCache(tmp_path), retries=1, **kw)
    p.client = httpx.Client(base_url="http://h:11434", transport=httpx.MockTransport(handler))
    return p


def test_ollama_request_and_cache(tmp_path):
    import httpx

    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"message": {"content": VALID}})

    p = _ollama(tmp_path, handler, num_ctx=4096)
    images = _images() + [LabeledImage(np.zeros((64, 64, 3), np.uint8), "Frame 2:")]
    assert p.analyze(images, "prompt", SceneAnalysis).ref_a == "hip"
    assert p.analyze(images, "prompt", SceneAnalysis).ref_a == "hip" and len(seen) == 1
    body = __import__("json").loads(seen[0].content)
    assert seen[0].url.path == "/api/chat" and body["model"] == "qwen3-vl:8b" and body["stream"] is False
    msg = body["messages"][0]
    assert msg["content"] == "Frame 1:[img]Frame 2:[img]prompt" and len(msg["images"]) == 2
    assert body["format"] == SceneAnalysis.model_json_schema() and body["options"]["num_ctx"] == 4096


def test_ollama_errors(tmp_path, monkeypatch):
    import httpx

    from funscript_gen.ai.base import ProviderError

    monkeypatch.setattr("funscript_gen.ai.openai_compat.time.sleep", lambda s: None)
    replies = [httpx.Response(503, text="busy"), httpx.Response(200, json={"message": {"content": VALID}})]
    p = _ollama(tmp_path / "a", lambda r: replies.pop(0))
    assert p.analyze(_images(), "prompt", SceneAnalysis).motion == "rhythmic"  # retried after the 503

    p = _ollama(tmp_path / "b", lambda r: httpx.Response(404, json={"error": "model 'qwen3-vl:8b' not found"}))
    with pytest.raises(ProviderError, match="not found"):
        p.analyze(_images(), "prompt", SceneAnalysis)

    full = lambda r: httpx.Response(400, json={  # noqa: E731 - what Ollama 0.40 answers
        "error": "request (4161 tokens) exceeds the available context size (4096 tokens), try increasing it"})
    with pytest.raises(ProviderError, match="VLLM_NUM_CTX=8192"):
        _ollama(tmp_path / "c", full).analyze(_images(), "prompt", SceneAnalysis)


def test_ollama_models_and_host():
    import httpx

    from funscript_gen.ai.ollama import OllamaProvider, ollama_host

    assert ollama_host("http://h:11434/v1/") == ollama_host("http://h:11434/api") == "http://h:11434"
    p = OllamaProvider("http://h:11434", "", "m")
    p.client = httpx.Client(base_url="http://h:11434", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"models": [{"name": "qwen3-vl:8b"}, {"name": "llava:7b"}]})))
    assert p.list_models() == ["qwen3-vl:8b", "llava:7b"]


def test_choice_probs_continue_the_answer_and_cache(tmp_path):
    from funscript_gen.ai.openai_compat import answer_prefix, choice_shares
    from funscript_gen.ai.prompts import FocusAnalysis

    answer = FocusAnalysis(apparent_minor=False, target_visible=True, frames=[], contact_part="hand",
                           focus_roi=None, shaft_base=None, shaft_tip=None, confidence=0.9)
    assert answer_prefix(answer, "contact_part").endswith('"frames": [],\n  "contact_part": "')
    top = {"hand": 0.6, "mouth": 0.3, "hands": 0.05, "v": 0.02, " mouth": 0.01}
    seen = []

    def create(**kw):
        seen.append(kw)
        tokens = [SimpleNamespace(token=t, logprob=float(np.log(p))) for t, p in top.items()]
        return SimpleNamespace(choices=[SimpleNamespace(logprobs=SimpleNamespace(
            content=[SimpleNamespace(token="hand", top_logprobs=tokens)]))])

    p = OpenAICompatProvider("http://x/v1", "k", "m", cache=ResponseCache(tmp_path), retries=1)
    p.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    for _ in range(2):
        probs = p.choice_probs(_images(), "prompt", FocusAnalysis, answer, "contact_part")
        assert probs["hand"] == pytest.approx(0.6) and probs["mouth"] == pytest.approx(0.3)
        assert probs["vagina"] == pytest.approx(0.02) and probs["anus"] == 0.0
    assert len(seen) == 1 and seen[0]["max_tokens"] == 1
    assert seen[0]["messages"][-1] == {"role": "assistant", "content": answer_prefix(answer, "contact_part")}
    # a token that starts several choices says nothing about which one
    assert choice_shares({"a": 0.5, "b": 0.5}, ("ab", "ac", "b")) == {"ab": 0.0, "ac": 0.0, "b": 0.5}


def test_cache_damaged_file_is_a_miss_and_put_leaves_no_temp_files(tmp_path):
    cache = ResponseCache(tmp_path)
    key = ResponseCache.key("m", "p", {}, [])
    (tmp_path / f"{key}.json").write_text('{"half": ', encoding="utf-8")
    assert cache.get(key) is None
    cache.put(key, {"a": 1})
    assert cache.get(key) == {"a": 1}
    assert [f.name for f in tmp_path.iterdir()] == [f"{key}.json"]
