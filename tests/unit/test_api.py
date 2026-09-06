"""FastAPI contract tests with dependency overrides; no live database required."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api.dependencies import get_database_engine, get_rag_answer_service
from app.api.main import app
from app.api.routes import analytics as analytics_routes
from real_estate_agent.analytics.models import (
    AppliedFilters,
    AreaMarketMetrics,
    ComparisonResult,
    DpeDistribution,
    MarketOverview,
)
from real_estate_agent.rag.embeddings.provider import EmbeddingProviderError
from real_estate_agent.rag.generation.models import AnswerCitation, RagAnswerResult


def _filters(arrondissement: int | None = None) -> AppliedFilters:
    return AppliedFilters(
        arrondissement=arrondissement,
        start_year=2021,
        end_year=2025,
        price_per_m2_min=1000,
        price_per_m2_max=50000,
        eligibility_policy="test policy",
    )


def _overview(arrondissement: int | None = None) -> MarketOverview:
    return MarketOverview(
        total_residential_transactions=100,
        price_eligible_transactions=95,
        market_analysis_transactions=90,
        excluded_outlier_count=5,
        median_price_per_m2=10348.84,
        raw_eligible_median_price_per_m2=10271.17,
        sensitivity_median_difference=77.67,
        median_residential_surface=43,
        price_p25=8750,
        price_p75=12147.02,
        filters=_filters(arrondissement),
    )


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_database_engine] = lambda: object()
    app.dependency_overrides[get_rag_answer_service] = lambda: object()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health_is_database_independent(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_openapi_documents_versioned_routes(client: TestClient):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/market/overview" in paths
    assert "/api/v1/dpe/distribution" in paths
    assert "/api/v1/areas/{arrondissement}/profile" in paths
    assert "/api/v1/rag/answer" in paths


def test_readiness_success(client: TestClient):
    class Result:
        def scalar_one(self) -> int:
            return 1

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _statement):
            return Result()

    class Engine:
        def connect(self):
            return Connection()

    app.dependency_overrides[get_database_engine] = lambda: Engine()
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "reachable"}


def test_readiness_failure_is_controlled(client: TestClient):
    class FailingEngine:
        def connect(self):
            raise RuntimeError("secret database detail")

    app.dependency_overrides[get_database_engine] = lambda: FailingEngine()
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_unavailable"
    assert "secret database detail" not in response.text


def test_market_overview_contract(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[object, int | None, int, int]] = []

    def fake_overview(engine, arrondissement, start_year, end_year):
        calls.append((engine, arrondissement, start_year, end_year))
        return _overview(arrondissement)

    monkeypatch.setattr(analytics_routes.service, "get_market_overview", fake_overview)
    response = client.get(
        "/api/v1/market/overview",
        params={"arrondissement": 13, "start_year": 2021, "end_year": 2025},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["median_price_per_m2"] == 10348.84
    assert payload["filters"]["arrondissement"] == 13
    assert calls[0][1:] == (13, 2021, 2025)


@pytest.mark.parametrize("arrondissement", [0, 21])
def test_invalid_arrondissement_returns_422(client: TestClient, arrondissement: int):
    response = client.get(
        "/api/v1/market/overview", params={"arrondissement": arrondissement}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"


def test_reversed_years_return_422(client: TestClient):
    response = client.get(
        "/api/v1/market/overview",
        params={"start_year": 2025, "end_year": 2021},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "analytics_input_error"


def test_comparison_repeated_parameters(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    def fake_comparison(_engine, areas, start_year, end_year):
        assert areas == [13, 20]
        return ComparisonResult(
            areas=[
                AreaMarketMetrics(
                    arrondissement=area,
                    total_residential_transactions=100,
                    market_analysis_transactions=90,
                    median_price_per_m2=9000 + area,
                    price_p25=8000,
                    price_p75=10000,
                    median_residential_surface=40,
                )
                for area in areas
            ],
            filters=_filters(),
        )

    monkeypatch.setattr(
        analytics_routes.service, "compare_arrondissements", fake_comparison
    )
    response = client.get(
        "/api/v1/market/compare",
        params=[
            ("arrondissements", "13"),
            ("arrondissements", "20"),
            ("start_year", "2021"),
            ("end_year", "2025"),
        ],
    )
    assert response.status_code == 200
    assert [area["arrondissement"] for area in response.json()["areas"]] == [13, 20]


def test_comparison_requires_two_distinct_areas(client: TestClient):
    response = client.get(
        "/api/v1/market/compare",
        params=[("arrondissements", "13"), ("arrondissements", "13")],
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "analytics_input_error"


def test_dpe_distribution_contract(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    result = DpeDistribution(
        eligible_dpe_count=100,
        counts={"A": 1, "B": 2, "C": 20, "D": 30, "E": 27, "F": 12, "G": 8},
        percentages={
            "A": 1,
            "B": 2,
            "C": 20,
            "D": 30,
            "E": 27,
            "F": 12,
            "G": 8,
        },
        f_count=12,
        g_count=8,
        fg_count=20,
        fg_percentage=20,
        start_year=2021,
        end_year=2025,
        includes_partial_year=False,
    )
    monkeypatch.setattr(
        analytics_routes.service,
        "get_dpe_distribution",
        lambda *_args: result,
    )
    response = client.get("/api/v1/dpe/distribution")
    assert response.status_code == 200
    assert response.json()["fg_percentage"] == 20


def test_invalid_dpe_scope_returns_422(client: TestClient):
    response = client.get(
        "/api/v1/dpe/distribution", params={"scope": "whole_building"}
    )
    assert response.status_code == 422


def test_database_failure_does_not_leak_details(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    def fail(*_args):
        raise OperationalError("SELECT secret", {"password": "hidden"}, RuntimeError())

    monkeypatch.setattr(analytics_routes.service, "get_market_overview", fail)
    response = client.get("/api/v1/market/overview")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "database_unavailable"
    assert "password" not in response.text
    assert "SELECT secret" not in response.text


def test_rag_answer_contract(client: TestClient):
    class FakeRagService:
        def answer(self, question: str, *, style: str) -> RagAnswerResult:
            assert question == "Combien de temps un DPE est-il valable ?"
            assert style == "brief"
            return RagAnswerResult(
                question=question,
                answer="Un DPE est généralement valable dix ans. [S1]",
                citations=[
                    AnswerCitation(
                        citation_id="S1",
                        chunk_id="dpe-001",
                        source_id="dpe_page_ministere",
                        title="Diagnostic de performance énergétique",
                        publisher="Ministère de la Transition écologique",
                        url="https://example.test/dpe",
                        section="Durée de validité",
                        page_start=None,
                        page_end=None,
                        similarity=0.81,
                    )
                ],
                retrieved_chunks=5,
                top_similarity=0.81,
                model="test-model",
                requested_style="brief",
                grounded=True,
                insufficient_context=False,
            )

    app.dependency_overrides[get_rag_answer_service] = lambda: FakeRagService()
    response = client.post(
        "/api/v1/rag/answer",
        json={
            "question": "  Combien de temps un DPE est-il valable ?  ",
            "style": "brief",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["grounded"] is True
    assert payload["citations"][0]["citation_id"] == "S1"


@pytest.mark.parametrize("message", ["Bonjour !", "Merci", "C'est OK."])
def test_social_messages_bypass_rag(client: TestClient, message: str):
    class RagMustNotRun:
        def answer(self, _question: str, *, style: str):
            del style
            raise AssertionError("RAG must not run for a social message")

    app.dependency_overrides[get_rag_answer_service] = lambda: RagMustNotRun()
    response = client.post(
        "/api/v1/rag/answer",
        json={"question": message, "style": "auto"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == "local-conversation-router"
    assert payload["citations"] == []
    assert payload["insufficient_context"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {"question": "   ", "style": "auto"},
        {"question": "Question", "style": "verbose"},
        {"question": "x" * 2_001, "style": "auto"},
    ],
)
def test_rag_request_validation(client: TestClient, payload: dict[str, str]):
    response = client.post("/api/v1/rag/answer", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation_error"


def test_rag_provider_failure_does_not_leak_details(client: TestClient):
    class FailingRagService:
        def answer(self, _question: str, *, style: str):
            del style
            raise EmbeddingProviderError("private provider detail")

    app.dependency_overrides[get_rag_answer_service] = lambda: FailingRagService()
    response = client.post(
        "/api/v1/rag/answer",
        json={"question": "Question valide", "style": "auto"},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ai_service_unavailable"
    assert "private provider detail" not in response.text
