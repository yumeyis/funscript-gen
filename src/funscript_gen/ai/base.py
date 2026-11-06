"""Provider-independent interface for vision-language models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeVar

import numpy as np
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ProviderError(RuntimeError):
    """The backend could not be reached or kept failing."""


class TransientError(ProviderError):
    """Connection failure, timeout, 5xx or 429: worth waiting and trying again (the cause is chained)."""


class InvalidResponse(ProviderError):
    """The model answered, but not with JSON matching the schema (often a refusal)."""

    def __init__(self, message: str, raw: str) -> None:
        super().__init__(message)
        self.raw = raw


@dataclass(slots=True)
class LabeledImage:
    image: np.ndarray  # BGR uint8
    label: str = ""  # shown to the model before the image, e.g. "t=12.3s"


class VisionProvider(Protocol):
    model: str

    def analyze(self, images: list[LabeledImage], prompt: str, schema: type[T]) -> T: ...

    def choice_probs(self, images: list[LabeledImage], prompt: str, schema: type[T], answer: T, field: str,
                     ) -> dict[str, float]: ...
