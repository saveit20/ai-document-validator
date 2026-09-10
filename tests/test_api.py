from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from helpers import golden_text

from validator.api import create_app
from validator.config import Settings
from validator.heuristic import HeuristicExtractor
from validator.pipeline import Pipeline

CONFIG = {
    "document_type": "SUPPLIER_INVOICE",
    "max_age_days": 90,
    "allowed_currencies": ["EUR", "GBP"],
    "required_fields": ["supplier_name", "invoice_number", "invoice_date", "total_amount"],
}


@pytest.fixture
def client() -> TestClient:
    heuristic = HeuristicExtractor()
    return TestClient(create_app(settings=Settings(), pipeline=Pipeline(heuristic, heuristic)))


def test_health_reports_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["X-Request-ID"]


def test_validate_json_text_returns_verdict(client: TestClient) -> None:
    body = {
        "document": {"text": golden_text("inv_01_clean_en")},
        "config": CONFIG,
        "reference_date": "2026-06-30",
    }
    response = client.post("/v1/validate", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "PASS"
    assert {rule["id"] for rule in data["rules"]} == {
        "invoice_date_max_age",
        "total_amount_positive",
        "supplier_name_present",
        "currency_allowed",
        "required_fields_present",
        "amounts_consistent",
    }
    assert Decimal(str(data["extraction"]["total_amount"]["value"])) == Decimal("1200")
    assert data["llm"] is None
    assert data["extractor_used"] == "heuristic"
    assert data["request_id"] == response.headers["X-Request-ID"]


def test_validate_rejects_invalid_config(client: TestClient) -> None:
    body = {"document": {"text": "x"}, "config": {**CONFIG, "max_age_days": 0}}
    response = client.post("/v1/validate", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
