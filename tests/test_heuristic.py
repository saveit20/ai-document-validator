from datetime import date
from decimal import Decimal

from helpers import fixture_text

from validator.extraction import build_extraction
from validator.heuristic import HeuristicExtractor
from validator.ingest import document_from_text
from validator.models import FIELD_NAMES


def extract(text: str):
    document = document_from_text(text)
    return build_extraction(HeuristicExtractor().extract(document).candidates, document)


def test_ignores_customer_block_for_supplier_and_tax_id() -> None:
    text = (
        "Bill to:\nNorthwind Construction S.L.\nVAT: ESB12345678\n\n"
        "From:\nDelta Hydraulics B.V.\nVAT number: NL853746214B01\n"
    )
    extraction = extract(text)
    assert extraction.supplier_name.value == "Delta Hydraulics B.V."
    assert extraction.tax_id.value == "NL853746214B01"
    assert extraction.customer_tax_id.value == "ESB12345678"


def test_customer_block_ends_without_blank_lines_as_in_pdf_text() -> None:
    text = (
        "Bill to:\nNorthwind Construction S.L.\nVAT: ESB12345678\n"
        "Subtotal 100.00\nVAT 21% 21.00\nTotal due: 121.00 EUR\n"
    )
    extraction = extract(text)
    assert extraction.customer_tax_id.value == "ESB12345678"
    assert extraction.total_amount.value == Decimal("121.00")
    assert extraction.tax_amount.value == Decimal("21.00")


def test_prefers_issue_date_over_due_date() -> None:
    extraction = extract("Due date: 2026-07-31\nInvoice date: 2026-06-01\n")
    assert extraction.invoice_date.value == date(2026, 6, 1)
    assert extraction.invoice_date.confidence == 1.0


def test_total_skips_subtotal_net_and_vat_lines() -> None:
    text = "Subtotal: 3,400.00 EUR\nVAT (21%): 714.00 EUR\nNet total 3,400.00\nAmount due: 4,114.00 EUR\n"
    extraction = extract(text)
    assert extraction.total_amount.value == Decimal("4114.00")
    assert extraction.currency.value == "EUR"


def test_unlabelled_date_is_ambiguous() -> None:
    extraction = extract("ACME Ltd\n2026-06-01\nTotal 10.00 EUR\n")
    assert extraction.invoice_date.value == date(2026, 6, 1)
    assert extraction.invoice_date.confidence == 0.6


def test_spanish_invoice() -> None:
    extraction = extract(fixture_text("inv_02_es_format"))
    assert extraction.supplier_name.value == "CONSTRUCCIONES Y REFORMAS GARCÍA S.L."
    assert extraction.invoice_number.value == "2026/0381"
    assert extraction.invoice_date.value == date(2026, 6, 3)
    assert extraction.total_amount.value == Decimal("1234.56")
    assert extraction.currency.value == "EUR"
    assert extraction.tax_id.value == "B87654321"


def test_missing_supplier_is_null() -> None:
    extraction = extract(fixture_text("inv_07_no_supplier"))
    assert extraction.supplier_name.value is None
    assert extraction.supplier_name.confidence == 0.0
    assert extraction.tax_id.value is None


def test_clean_invoice_is_fully_confident() -> None:
    extraction = extract(fixture_text("inv_01_clean_en"))
    assert extraction.total_amount.value == Decimal("1200.00")
    assert extraction.tax_id.value == "GB123456789"
    assert all(extraction.field(name).confidence == 1.0 for name in FIELD_NAMES)


def test_extracts_subtotal_tax_and_customer() -> None:
    extraction = extract(fixture_text("inv_09_gbp_long_date"))
    assert extraction.subtotal_amount.value == Decimal("2000.00")
    assert extraction.tax_amount.value == Decimal("400.00")
    assert extraction.customer_name.value == "Northwind Construction UK Ltd"


def test_withholding_is_not_tax_and_customer_id_comes_from_customer_block() -> None:
    extraction = extract(fixture_text("inv_14_irpf_withholding"))
    assert extraction.supplier_name.value == "Estudio de Arquitectura Rivas S.L.P."
    assert extraction.tax_amount.value == Decimal("210.00")
    assert extraction.total_amount.value == Decimal("1060.00")
    assert extraction.customer_tax_id.value == "B12345678"
    assert extraction.tax_id.value == "B28456781"
