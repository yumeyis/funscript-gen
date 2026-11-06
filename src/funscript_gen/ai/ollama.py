"""Ollama native API provider (/api/chat).

Ollama's /v1 can neither set the context length (its default, 4096 on an 8 GB GPU, rejects 4 images: Qwen3-VL images
take about 1040 tokens each there, whatever their size) nor keep a label in front of its image (all images go first).
"""

from __future__ import annotations

import base64
import re

import httpx

from funscript_gen.ai.base import LabeledImage, ProviderError, TransientError
from funscript_gen.ai.cache import ResponseCache
from funscript_gen.ai.openai_compat import OpenAICompatProvider


def ollama_host(base_url: str) -> str:
    """'http://h:11434', '.../v1' or '.../api' -> 'http://h:11434' (the OpenAI-style URL works too)."""
    return re.sub(r"/(v1|api)/?$", "", base_url.rstrip("/"))


class OllamaProvider(OpenAICompatProvider):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        num_ctx: int = 8192,
        image_max_side: int = 768,
        timeout_s: float = 120.0,
        retries: int = 2,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        cache: ResponseCache | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}  # for a proxy in front of Ollama
        self.client = httpx.Client(base_url=ollama_host(base_url), headers=headers, timeout=timeout_s)
        self.model = model
        self.num_ctx = num_ctx
        self.image_max_side = image_max_side
        self.retries = retries
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.cache = cache or ResponseCache()
        self.last_latency_s = 0.0

    def _send(self, path: str, payload: dict | None = None) -> dict:
        """POST the payload (GET without one) -> the JSON reply."""
        try:
            resp = self.client.post(path, json=payload) if payload is not None else self.client.get(path)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as e:
            raise TransientError() from e
        if resp.status_code >= 500 or resp.status_code == 429:
            raise TransientError() from ProviderError(f"{resp.status_code}: {resp.text[:200]}")
        if resp.status_code != 200:
            try:
                message = resp.json().get("error", resp.text)
            except ValueError:
                message = resp.text
            if "context size" in message:
                message += f" (VLLM_NUM_CTX={self.num_ctx})"
            raise ProviderError(f"{resp.status_code}: {message}")
        return resp.json()

    def _complete(self, images: list[LabeledImage], jpegs: list[bytes], prompt: str, name: str, json_schema: dict) -> str:
        # Each "[img]" is replaced by the next image, so every label stays in front of its image.
        text = "".join(f"{li.label}[img]" for li in images) + prompt
        return self._send("/api/chat", {
            "model": self.model,
            "messages": [{"role": "user", "content": text, "images": [base64.b64encode(j).decode() for j in jpegs]}],
            "format": json_schema,
            "stream": False,
            "options": {"temperature": self.temperature, "num_predict": self.max_tokens, "num_ctx": self.num_ctx},
        }).get("message", {}).get("content", "")

    def choice_probs(self, images, prompt, schema, answer, field) -> dict[str, float]:
        raise ProviderError("the Ollama backend gives no answer probabilities")

    def list_models(self) -> list[str]:
        try:
            return [m["name"] for m in self._send("/api/tags").get("models", [])]
        except TransientError as e:
            raise ProviderError(str(e.__cause__)) from e
