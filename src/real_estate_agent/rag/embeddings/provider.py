"""Small, testable boundary around the OpenAI embeddings API."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Protocol


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding provider returns an unusable response."""


class EmbeddingProvider(Protocol):
    """Provider-neutral contract used by the indexing pipeline."""

    model: str
    dimensions: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one fixed-size embedding for every input text."""


class OpenAIEmbeddingProvider:
    """Generate deterministic-size vectors through the OpenAI API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        dimensions: int,
        timeout_seconds: float = 60.0,
        client: Any | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("An OpenAI API key is required.")
        self.model = model
        self.dimensions = dimensions
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - dependency setup failure
                raise EmbeddingProviderError(
                    "The openai package is missing. Install .[database,rag]."
                ) from exc
            self._client = OpenAI(
                api_key=self._api_key,
                timeout=self._timeout_seconds,
                max_retries=3,
            )
        return self._client

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        values = list(texts)
        if not values:
            return []
        if any(not text.strip() for text in values):
            raise EmbeddingProviderError("Blank text cannot be embedded.")

        try:
            response = self._get_client().embeddings.create(
                model=self.model,
                input=values,
                dimensions=self.dimensions,
                encoding_format="float",
            )
        except Exception as exc:
            raise EmbeddingProviderError(f"OpenAI embeddings request failed: {exc}") from exc

        ordered = sorted(response.data, key=lambda item: item.index)
        if [item.index for item in ordered] != list(range(len(values))):
            raise EmbeddingProviderError("OpenAI returned missing or unexpected result indexes.")

        vectors: list[list[float]] = []
        for item in ordered:
            vector = [float(value) for value in item.embedding]
            if len(vector) != self.dimensions:
                raise EmbeddingProviderError(
                    f"Expected {self.dimensions} dimensions, received {len(vector)}."
                )
            if not all(math.isfinite(value) for value in vector):
                raise EmbeddingProviderError("OpenAI returned a non-finite embedding value.")
            vectors.append(vector)
        return vectors
