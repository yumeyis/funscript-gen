"""OpenAI Chat Completions compatible provider (vLLM, LM Studio, Ollama /v1, OpenRouter, ...)."""

from __future__ import annotations

import base64
import json
import math
import re
import time
from typing import get_args

import cv2
import numpy as np
from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI
from pydantic import BaseModel, ValidationError

from funscript_gen.ai.base import InvalidResponse, LabeledImage, ProviderError, T, TransientError
from funscript_gen.ai.cache import ResponseCache


def encode_jpeg(image: np.ndarray, max_side: int, quality: int = 85) -> bytes:
    h, w = image.shape[:2]
    k = max_side / max(h, w)
    if k < 1:
        image = cv2.resize(image, (round(w * k), round(h * k)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("JPEG encoding failed")
    return buf.tobytes()


def _extract_json(text: str) -> str:
    """Strip markdown fences / chatter around a JSON object."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group(0) if m else text


def answer_prefix(answer: BaseModel, field: str) -> str:
    """The answer's JSON up to the opening quote of `field`'s value, laid out as the model writes it (guided decoding
    indents by 2), so the model can be asked to continue from there."""
    text = json.dumps(answer.model_dump(mode="json"), indent=2, ensure_ascii=False)
    head = f'"{field}": "'
    return text[:text.index(head) + len(head)]


def choice_shares(top: dict[str, float], choices: tuple[str, ...]) -> dict[str, float]:
    """First-token probabilities -> probability per choice. A token counts for the one choice it starts (\"v\" for
    \"vagina\"); tokens that start none (\"hands\", \" mouth\": the JSON grammar rejects them) or several are dropped."""
    out = dict.fromkeys(choices, 0.0)
    for token, p in top.items():
        hits = [c for c in choices if token and c.startswith(token)]
        if len(hits) == 1:
            out[hits[0]] += p
    return out


class OpenAICompatProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        image_max_side: int = 768,
        timeout_s: float = 120.0,
        retries: int = 2,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        cache: ResponseCache | None = None,
    ) -> None:
        self.client = OpenAI(base_url=base_url, api_key=api_key or "EMPTY", timeout=timeout_s, max_retries=0)
        self.model = model
        self.image_max_side = image_max_side
        self.retries = retries
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.cache = cache or ResponseCache()
        self.last_latency_s = 0.0

    def analyze(self, images: list[LabeledImage], prompt: str, schema: type[T]) -> T:
        json_schema = schema.model_json_schema()
        jpegs = [encode_jpeg(li.image, self.image_max_side) for li in images]
        key = ResponseCache.key(self.model, prompt, json_schema, jpegs)
        cached = self.cache.get(key)
        if cached is not None:
            self.last_latency_s = 0.0
            return schema.model_validate(cached)

        last_error: Exception | None = None
        raw = ""
        for attempt in range(self.retries + 1):
            try:
                t0 = time.monotonic()
                raw = self._complete(images, jpegs, prompt, schema.__name__, json_schema)
                self.last_latency_s = time.monotonic() - t0
            except TransientError as e:
                last_error = e.__cause__ or e
                time.sleep(min(2**attempt, 8))
                continue
            try:
                result = schema.model_validate(json.loads(_extract_json(raw)))
            except (json.JSONDecodeError, ValidationError) as e:
                last_error = e
                continue  # sampling is deterministic, but guided decoding can still truncate; retry once more
            self.cache.put(key, result.model_dump(mode="json"))
            return result

        if raw:
            raise InvalidResponse(f"model output did not match {schema.__name__}: {last_error}", raw)
        raise ProviderError(f"request failed after {self.retries + 1} attempts: {last_error}")

    def choice_probs(self, images: list[LabeledImage], prompt: str, schema: type[T], answer: T, field: str,
                     ) -> dict[str, float]:
        """How likely each value of `answer`'s Literal `field` was: the model continues `answer` (the reply to the same
        images, prompt and schema) from the opening quote of that value for one token, and the top tokens'
        probabilities are summed per value. Conditioned on the answer's earlier fields, so its own value comes first.
        Needs a server that continues an assistant message and returns logprobs (vLLM)."""
        choices = get_args(schema.model_fields[field].annotation)
        prefix = answer_prefix(answer, field)
        jpegs = [encode_jpeg(li.image, self.image_max_side) for li in images]
        key = ResponseCache.key(self.model, f"{prompt}\0{prefix}", schema.model_json_schema(), jpegs)
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                top = self._next_token(images, jpegs, prompt, prefix)
            except TransientError as e:
                last_error = e.__cause__ or e
                time.sleep(min(2**attempt, 8))
                continue
            probs = choice_shares(top, choices)
            self.cache.put(key, probs)
            return probs
        raise ProviderError(f"request failed after {self.retries + 1} attempts: {last_error}")

    def _content(self, images: list[LabeledImage], jpegs: list[bytes], prompt: str) -> list[dict]:
        content: list[dict] = []
        for li, jpg in zip(images, jpegs):
            if li.label:
                content.append({"type": "text", "text": li.label})
            url = "data:image/jpeg;base64," + base64.b64encode(jpg).decode()
            content.append({"type": "image_url", "image_url": {"url": url}})
        content.append({"type": "text", "text": prompt})
        return content

    def _create(self, **kw):
        try:
            return self.client.chat.completions.create(model=self.model, temperature=self.temperature, **kw)
        except (APIConnectionError, APITimeoutError) as e:
            raise TransientError() from e
        except APIStatusError as e:
            if e.status_code >= 500 or e.status_code == 429:
                raise TransientError() from e
            raise ProviderError(f"{e.status_code}: {e.message}") from e

    def _complete(self, images: list[LabeledImage], jpegs: list[bytes], prompt: str, name: str, json_schema: dict) -> str:
        """One request -> the model's text. Raises TransientError when it is worth trying again."""
        resp = self._create(
            messages=[{"role": "user", "content": self._content(images, jpegs, prompt)}],
            response_format={"type": "json_schema", "json_schema": {"name": name, "schema": json_schema}},
            max_tokens=self.max_tokens,
        )
        return resp.choices[0].message.content or ""

    def _next_token(self, images: list[LabeledImage], jpegs: list[bytes], prompt: str, prefix: str) -> dict[str, float]:
        """The model's reply continued from `prefix`: its most likely next tokens and their probabilities."""
        resp = self._create(
            messages=[{"role": "user", "content": self._content(images, jpegs, prompt)},
                      {"role": "assistant", "content": prefix}],
            max_tokens=1,
            logprobs=True,
            top_logprobs=20,
            extra_body={"continue_final_message": True, "add_generation_prompt": False},
        )
        logprobs = resp.choices[0].logprobs
        if logprobs is None or not logprobs.content:
            raise ProviderError("the server returned no logprobs")
        return {t.token: math.exp(t.logprob) for t in logprobs.content[0].top_logprobs}

    def list_models(self) -> list[str]:
        return [m.id for m in self.client.models.list().data]
