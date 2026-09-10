import json
import logging
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from helpers import GOLDEN_DIR, golden_text

from validator.api import create_app
from validator.config import Settings
from validator.heuristic import HeuristicExtractor
from validator.ingest import MAX_DOCUMENT_BYTES
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


def test_validate_multipart_text_matches_json(client: TestClient) -> None:
    text = golden_text("inv_01_clean_en")
    response = client.post(
        "/v1/validate",
        files={"file": ("invoice.txt", text.encode(), "text/plain")},
        data={"config": json.dumps(CONFIG), "reference_date": "2026-06-30"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "PASS"


def test_validate_multipart_pdf(client: TestClient) -> None:
    pdf = (GOLDEN_DIR / "inv_10_pdf.pdf").read_bytes()
    response = client.post(
        "/v1/validate",
        files={"file": ("invoice.pdf", pdf, "application/pdf")},
        data={"config": json.dumps(CONFIG), "reference_date": "2026-06-30"},
    )
    assert response.status_code == 200
    assert response.json()["extraction"]["total_amount"]["page"] == 1


def test_extract_returns_fields_without_rules(client: TestClient) -> None:
    response = client.post(
        "/v1/extract", json={"document": {"text": golden_text("inv_01_clean_en")}}
    )
    assert response.status_code == 200
    assert "rules" not in response.json()
    assert response.json()["extraction"]["supplier_name"]["value"]


def test_unsupported_file_type_is_415(client: TestClient) -> None:
    response = client.post("/v1/extract", files={"file": ("x.png", b"PNGDATA", "image/png")})
    assert response.status_code == 415
    assert response.json()["error"]["code"]


def test_document_too_large_is_413(client: TestClient) -> None:
    big = b"a" * (MAX_DOCUMENT_BYTES + 1)
    response = client.post("/v1/extract", files={"file": ("big.txt", big, "text/plain")})
    assert response.status_code == 413


def test_multipart_config_must_be_json(client: TestClient) -> None:
    response = client.post(
        "/v1/validate",
        files={"file": ("x.txt", b"Invoice", "text/plain")},
        data={"config": "not json"},
    )
    assert response.status_code == 422


def test_openapi_documents_both_body_types_for_both_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths) == {"/health", "/v1/validate", "/v1/extract"}
    for route in ("/v1/validate", "/v1/extract"):
        content = paths[route]["post"]["requestBody"]["content"]
        assert set(content) == {"application/json", "multipart/form-data"}


@pytest.mark.parametrize("supplied", ["x" * 65, "bad id\nwith newline"])
def test_unsafe_request_id_is_replaced(client: TestClient, supplied: str) -> None:
    response = client.get("/health", headers={"X-Request-ID": supplied})
    assert response.headers["X-Request-ID"] != supplied
    assert len(response.headers["X-Request-ID"]) == 32


def test_validate_rejects_invalid_config(client: TestClient) -> None:
    body = {"document": {"text": "x"}, "config": {**CONFIG, "max_age_days": 0}}
    response = client.post("/v1/validate", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
