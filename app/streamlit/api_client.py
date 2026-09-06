"""HTTP client used by Streamlit to consume the local FastAPI backend."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

DEFAULT_API_BASE_URL = "http://localhost:8000"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_AI_TIMEOUT_SECONDS = 180.0


class ApiClientError(RuntimeError):
    """User-displayable API communication error."""


def common_query_params(
    arrondissement: int | None,
    start_year: int,
    end_year: int,
) -> dict[str, int | str]:
    """Build shared validated-looking parameters; the API remains authoritative."""
    params = {"start_year": start_year, "end_year": end_year}
    if arrondissement is not None:
        params["arrondissement"] = arrondissement
    return params


def comparison_query_params(
    arrondissements: Sequence[int],
    start_year: int,
    end_year: int,
) -> dict[str, int | list[int]]:
    """Build repeated-list parameters understood by FastAPI/httpx."""
    return {
        "arrondissements": list(arrondissements),
        "start_year": start_year,
        "end_year": end_year,
    }


class RealEstateApiClient:
    """Small typed boundary around the application's read-only HTTP endpoints."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        ai_timeout_seconds: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        configured_url = base_url or os.getenv("API_BASE_URL", DEFAULT_API_BASE_URL)
        if not configured_url.startswith(("http://", "https://")):
            raise ValueError("API_BASE_URL must start with http:// or https://")

        configured_timeout = timeout_seconds
        if configured_timeout is None:
            raw_timeout = os.getenv(
                "API_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)
            )
            try:
                configured_timeout = float(raw_timeout)
            except ValueError as exc:
                raise ValueError("API_TIMEOUT_SECONDS must be numeric") from exc
        if configured_timeout <= 0:
            raise ValueError("API_TIMEOUT_SECONDS must be greater than zero")

        configured_ai_timeout = ai_timeout_seconds
        if configured_ai_timeout is None:
            raw_ai_timeout = os.getenv(
                "AI_API_TIMEOUT_SECONDS", str(DEFAULT_AI_TIMEOUT_SECONDS)
            )
            try:
                configured_ai_timeout = float(raw_ai_timeout)
            except ValueError as exc:
                raise ValueError("AI_API_TIMEOUT_SECONDS must be numeric") from exc
        if configured_ai_timeout <= 0:
            raise ValueError("AI_API_TIMEOUT_SECONDS must be greater than zero")

        self.base_url = configured_url.rstrip("/")
        self._default_timeout_seconds = configured_timeout
        self._ai_timeout_seconds = configured_ai_timeout
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=configured_timeout,
            transport=transport,
            trust_env=False,
        )

    def close(self) -> None:
        """Close pooled HTTP connections."""
        self._client.close()

    def get_json(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET one JSON object and convert transport/HTTP failures safely."""
        try:
            response = self._client.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise ApiClientError(
                "L'API met trop de temps à répondre. Réessayez dans un instant."
            ) from exc
        except httpx.RequestError as exc:
            raise ApiClientError(
                "Impossible de joindre FastAPI. Vérifiez que le serveur est démarré."
            ) from exc

        if response.is_error:
            message = "La requête a échoué."
            try:
                payload = response.json()
                message = payload.get("error", {}).get("message", message)
            except (ValueError, AttributeError):
                pass
            raise ApiClientError(f"Erreur API {response.status_code} : {message}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiClientError("L'API a renvoyé une réponse JSON invalide.") from exc
        if not isinstance(payload, dict):
            raise ApiClientError("L'API a renvoyé un format inattendu.")
        return payload

    def post_json(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """POST one JSON object and convert transport/HTTP failures safely."""
        try:
            response = self._client.post(
                path,
                json=dict(payload),
                timeout=timeout_seconds or self._default_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ApiClientError(
                "L’assistant met trop de temps à répondre. Réessayez dans un instant."
            ) from exc
        except httpx.RequestError as exc:
            raise ApiClientError(
                "Impossible de joindre FastAPI. Vérifiez que le serveur est démarré."
            ) from exc

        if response.is_error:
            message = "La requête a échoué."
            try:
                response_payload = response.json()
                message = response_payload.get("error", {}).get("message", message)
            except (ValueError, AttributeError):
                pass
            raise ApiClientError(f"Erreur API {response.status_code} : {message}")

        try:
            response_payload = response.json()
        except ValueError as exc:
            raise ApiClientError("L’API a renvoyé une réponse JSON invalide.") from exc
        if not isinstance(response_payload, dict):
            raise ApiClientError("L’API a renvoyé un format inattendu.")
        return response_payload

    def market_overview(
        self, arrondissement: int | None, start_year: int, end_year: int
    ) -> dict[str, Any]:
        return self.get_json(
            "/api/v1/market/overview",
            common_query_params(arrondissement, start_year, end_year),
        )

    def market_trends(
        self, arrondissement: int | None, start_year: int, end_year: int
    ) -> dict[str, Any]:
        return self.get_json(
            "/api/v1/market/trends",
            common_query_params(arrondissement, start_year, end_year),
        )

    def market_rankings(self, start_year: int, end_year: int) -> dict[str, Any]:
        return self.get_json(
            "/api/v1/market/rankings",
            {"start_year": start_year, "end_year": end_year},
        )

    def market_comparison(
        self, arrondissements: Sequence[int], start_year: int, end_year: int
    ) -> dict[str, Any]:
        return self.get_json(
            "/api/v1/market/compare",
            comparison_query_params(arrondissements, start_year, end_year),
        )

    def dpe_distribution(
        self, arrondissement: int | None, start_year: int, end_year: int
    ) -> dict[str, Any]:
        params = common_query_params(arrondissement, start_year, end_year)
        params["scope"] = "dwelling_unit"
        return self.get_json("/api/v1/dpe/distribution", params)

    def dpe_intensity(
        self, arrondissement: int | None, start_year: int, end_year: int
    ) -> dict[str, Any]:
        params = common_query_params(arrondissement, start_year, end_year)
        params["scope"] = "dwelling_unit"
        return self.get_json("/api/v1/dpe/intensity", params)

    def area_profile(
        self, arrondissement: int, start_year: int, end_year: int
    ) -> dict[str, Any]:
        return self.get_json(
            f"/api/v1/areas/{arrondissement}/profile",
            {"start_year": start_year, "end_year": end_year},
        )

    def ask_rag(self, question: str, style: str = "auto") -> dict[str, Any]:
        """Ask one independent question against the official document corpus."""
        return self.post_json(
            "/api/v1/rag/answer",
            {"question": question, "style": style},
            timeout_seconds=self._ai_timeout_seconds,
        )

    def ask_agent(
        self,
        message: str,
        history: Sequence[Mapping[str, str]] = (),
    ) -> dict[str, Any]:
        """Send one turn and bounded session history to the multi-tool agent."""
        bounded_history = [
            {
                "role": str(item.get("role", "")),
                "content": str(item.get("content", "")),
            }
            for item in list(history)[-12:]
        ]
        return self.post_json(
            "/api/v1/agent/chat",
            {"message": message, "history": bounded_history},
            timeout_seconds=self._ai_timeout_seconds,
        )
