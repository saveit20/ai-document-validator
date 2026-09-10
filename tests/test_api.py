import json
import logging
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from helpers import golden_text

from validator.api import create_app
from validator.config import Settings
from validator.heuristic import HeuristicExtractor
from validator.observability import JsonFormatter
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


def test_each_request_logs_one_json_line_with_id_latency_model_and_verdict(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="validator.api")
    body = {
        "document": {"text": golden_text("inv_01_clean_en")},
        "config": CONFIG,
        "reference_date": "2026-06-30",
    }
    response = client.post("/v1/validate", json=body, headers={"X-Request-ID": "log-check"})
    lines = [
        json.loads(JsonFormatter().format(record))
        for record in caplog.records
        if getattr(record, "request_id", None) == "log-check"
    ]
    assert len(lines) == 1
    line = lines[0]
    assert line["event"] == "request_completed"
    assert line["latency_ms"] >= 0
    assert line["verdict"] == response.json()["status"]
    assert line["extractor_used"] == "heuristic"
    assert "model" in line
    assert "Northwind" not in json.dumps(line)


def test_validate_rejects_invalid_config(client: TestClient) -> None:
    body = {"document": {"text": "x"}, "config": {**CONFIG, "max_age_days": 0}}
    response = client.post("/v1/validate", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
