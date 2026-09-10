import json
from datetime import date
from decimal import Decimal

import pytest
from fpdf import FPDF

from validator.confidence import score
from validator.extraction import Candidate, build_extraction
from validator.ingest import (
    DocumentTooLarge,
    UnreadableDocument,
    UnsupportedMediaType,
    document_from_bytes,
    document_from_text,
)

DOC = "ACME Ltd\nTotal due: EUR 1.500\nInvoice date: 2026-06-15\n"


def _score(field, value, raw, evidence, ambiguous=False):
    return score(field, value, raw=raw, evidence=evidence, ambiguous=ambiguous, document_text=DOC)


def test_missing_field_scores_zero() -> None:
    assert _score("invoice_date", None, None, None) == 0.0


def test_found_but_unparseable_scores_low() -> None:
    assert _score("invoice_date", None, "soon", "soon") == 0.3


def test_grounded_value_scores_high() -> None:
    assert (
        _score("invoice_date", date(2026, 6, 15), "2026-06-15", "Invoice date: 2026-06-15") == 1.0
    )


def test_evidence_absent_from_document_scores_low() -> None:
    assert (
        _score("invoice_date", date(2026, 6, 16), "2026-06-16", "Invoice date: 2026-06-16") == 0.3
    )


def test_value_not_supported_by_real_evidence_scores_low() -> None:
    assert (
        _score("invoice_date", date(2026, 6, 16), "2026-06-16", "Invoice date: 2026-06-15") == 0.3
    )


def test_ambiguous_amount_format_scores_medium() -> None:
    assert _score("total_amount", Decimal("1500"), "1500", "Total due: EUR 1.500") == 0.6


def test_competing_candidates_score_medium() -> None:
    evidence = "Invoice date: 2026-06-15"
    assert _score("invoice_date", date(2026, 6, 15), "2026-06-15", evidence, ambiguous=True) == 0.6


def test_build_extraction_normalises_and_locates_page() -> None:
    document = document_from_text("Total due (EUR) 1,200.00")
    extraction = build_extraction(
        {"total_amount": Candidate(raw="1,200.00", evidence="Total due (EUR) 1,200.00")}, document
    )
    assert extraction.total_amount.value == Decimal("1200.00")
    assert extraction.total_amount.confidence == 1.0
    assert extraction.total_amount.page == 1
    assert extraction.supplier_name.value is None
    assert json.loads(extraction.model_dump_json())["total_amount"]["value"] == 1200.0


def test_text_document_too_large_is_rejected() -> None:
    with pytest.raises(DocumentTooLarge):
        document_from_text("a" * (5 * 1024 * 1024 + 1))


def test_empty_text_is_unreadable() -> None:
    with pytest.raises(UnreadableDocument):
        document_from_text("   \n ")


def test_unsupported_media_type() -> None:
    with pytest.raises(UnsupportedMediaType):
        document_from_bytes(b"\x89PNG....", "image/png")


def test_pdf_without_text_layer_is_unreadable() -> None:
    pdf = FPDF()
    pdf.add_page()
    with pytest.raises(UnreadableDocument):
        document_from_bytes(bytes(pdf.output()), "application/pdf")


def test_corrupt_pdf_is_unreadable() -> None:
    with pytest.raises(UnreadableDocument):
        document_from_bytes(b"%PDF-1.7 this is not a pdf", "application/pdf")
