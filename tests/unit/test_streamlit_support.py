"""Tests for the dashboard's HTTP boundary and presentation helpers."""

from __future__ import annotations

import httpx
import pytest

from app.streamlit.api_client import (
    ApiClientError,
    RealEstateApiClient,
    common_query_params,
    comparison_query_params,
)
from app.streamlit.formatters import (
    arrondissement_label,
    format_euro_per_m2,
    format_integer,
    format_percentage,
    format_surface,
)


def test_query_parameter_builders():
    assert common_query_params(None, 2021, 2025) == {
        "start_year": 2021,
        "end_year": 2025,
    }
    assert common_query_params(13, 2021, 2025)["arrondissement"] == 13
    assert comparison_query_params([13, 20], 2021, 2025)["arrondissements"] == [
        13,
        20,
    ]


def test_client_sends_repeated_comparison_parameters():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/market/compare"
        assert request.url.params.get_list("arrondissements") == ["13", "20"]
        return httpx.Response(200, json={"areas": []})

    client = RealEstateApiClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    )
    try:
        assert client.market_comparison([13, 20], 2021, 2025) == {"areas": []}
    finally:
        client.close()


def test_client_posts_documentary_question_to_rag_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/rag/answer"
        assert request.read() == b'{"question":"Validite du DPE ?","style":"brief"}'
        return httpx.Response(
            200,
            json={
                "question": "Validite du DPE ?",
                "answer": "Dix ans. [S1]",
                "citations": [],
                "insufficient_context": False,
            },
        )

    client = RealEstateApiClient(
        base_url="http://test",
        ai_timeout_seconds=30,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = client.ask_rag("Validite du DPE ?", "brief")
        assert result["answer"] == "Dix ans. [S1]"
    finally:
        client.close()


def test_client_surfaces_controlled_api_message():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            json={"error": {"message": "The database service is unavailable."}},
        )

    client = RealEstateApiClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(ApiClientError, match="database service"):
            client.market_overview(None, 2021, 2025)
    finally:
        client.close()


def test_client_converts_connection_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = RealEstateApiClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises(ApiClientError, match="Impossible de joindre FastAPI"):
            client.market_overview(None, 2021, 2025)
    finally:
        client.close()


def test_client_rejects_invalid_configuration():
    with pytest.raises(ValueError, match="http"):
        RealEstateApiClient(base_url="localhost:8000")
    with pytest.raises(ValueError, match="greater than zero"):
        RealEstateApiClient(base_url="http://test", timeout_seconds=0)
    with pytest.raises(ValueError, match="AI_API_TIMEOUT_SECONDS"):
        RealEstateApiClient(base_url="http://test", ai_timeout_seconds=0)


def test_dashboard_formatters():
    assert format_integer(160977) == "160 977"
    assert format_euro_per_m2(10348.84) == "10 349 €/m²"
    assert format_surface(43) == "43.0 m²"
    assert format_percentage(1.25, signed=True) == "+1.25 %"
    assert format_percentage(None) == "N/D"
    assert arrondissement_label(None) == "Paris entier"
    assert arrondissement_label(1) == "Paris 1er"
    assert arrondissement_label(20) == "Paris 20e"
