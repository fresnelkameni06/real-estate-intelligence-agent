"""Small testable boundary around the OpenAI Responses API."""

from __future__ import annotations

from typing import Any, Protocol


class ResponseGenerationError(RuntimeError):
    """Raised when the text-generation provider returns no usable answer."""


class ResponseGenerator(Protocol):
    """Provider-neutral contract used by the grounded answer service."""

    model: str

    def generate(
        self,
        *,
        instructions: str,
        input_text: str,
        max_output_tokens: int,
    ) -> str:
        """Generate one answer from trusted instructions and bounded context."""


class OpenAIResponsesGenerator:
    """Generate text through OpenAI's Responses API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
        client: Any | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("An OpenAI API key is required.")
        if not model.strip():
            raise ValueError("An OpenAI chat model is required.")
        self.model = model.strip()
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover - dependency setup failure
                raise ResponseGenerationError(
                    "The openai package is missing. Install .[database,rag]."
                ) from exc
            self._client = OpenAI(
                api_key=self._api_key,
                timeout=self._timeout_seconds,
                max_retries=3,
            )
        return self._client

    def generate(
        self,
        *,
        instructions: str,
        input_text: str,
        max_output_tokens: int,
    ) -> str:
        if not instructions.strip() or not input_text.strip():
            raise ValueError("Instructions and input text must not be blank.")
        try:
            response = self._get_client().responses.create(
                model=self.model,
                instructions=instructions,
                input=input_text,
                max_output_tokens=max_output_tokens,
                reasoning={"effort": "low"},
                store=False,
            )
        except Exception as exc:
            raise ResponseGenerationError(
                "OpenAI answer generation failed. Check the model, API access and quota."
            ) from exc

        if getattr(response, "status", None) == "incomplete":
            raise ResponseGenerationError(
                "OpenAI returned an incomplete answer. Increase "
                "OPENAI_CHAT_MAX_OUTPUT_TOKENS or request a shorter response."
            )
        output = str(getattr(response, "output_text", "")).strip()
        if not output:
            raise ResponseGenerationError("OpenAI returned an empty text answer.")
        return output
