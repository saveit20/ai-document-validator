import pytest
from helpers import FakeTransport, llm_reply

from validator.confidence import supports
from validator.heuristic import HeuristicExtractor
from validator.ingest import document_from_text
from validator.llm import LLMExtractor
from validator.pipeline import Pipeline


@pytest.mark.parametrize(
    ("field", "value", "evidence"),
    [
        ("invoice_number", "DH/2026/0419", "Invoice no. DH/2026/0419"),
        ("invoice_number", "INV-2026-005", "Invoice: INV-2026-005"),
        ("tax_id", "NL853746214B01", "BTW: NL853746214B01"),
        ("tax_id", "9015852843", "NIT: (CO) 901.585.284-3"),
        ("supplier_name", "Delta Hydraulics B.V.", "Delta Hydraulics B.V., Rotterdam"),
        ("supplier_name", "Gregory, Patterson and Fischer", " Gregory, Patterson and Fischer"),
        # Text layers glue a number to the neighbouring word; the number is still whole.
        ("invoice_number", "AV-2024-001", "Credit noteAV-2024-001"),
        ("invoice_number", "2015738820", "2015738820Rechnungsnummer:"),
    ],
)
def test_whole_values_are_confident(field: str, value: str, evidence: str) -> None:
    assert supports(field, value, evidence) == (True, False)


@pytest.mark.parametrize(
    ("field", "value", "evidence"),
    [
        ("invoice_number", "2026", "Invoice no. DH/2026/0419"),
        ("tax_id", "NL853746214", "BTW: NL853746214B01"),
        ("tax_id", "853746214", "BTW: NL853746214"),
        ("supplier_name", "Delta Hydrau", "Delta Hydraulics B.V."),
    ],
)
def test_a_fragment_of_the_evidence_is_grounded_but_doubtful(
    field: str, value: str, evidence: str
) -> None:
    assert supports(field, value, evidence) == (True, True)


def test_customer_quoted_from_the_supplier_block_is_doubtful() -> None:
    document = document_from_text(
        "INVOICE\nFrom: Alpha Supplies Ltd, VAT GB111111111\nBill to: Beta Buyers Ltd\n"
        "Invoice number: A-1\nInvoice date: 2026-06-01\nTotal: 100.00 EUR\n"
    )
    reply = llm_reply(
        supplier_name=("Alpha Supplies Ltd", "From: Alpha Supplies Ltd"),
        customer_tax_id=("GB111111111", "From: Alpha Supplies Ltd, VAT GB111111111"),
    )
    pipeline = Pipeline(LLMExtractor(FakeTransport(reply), "claude-opus-5"), HeuristicExtractor())
    extraction = pipeline.extract(document).extraction
    assert extraction.customer_tax_id.confidence < 1.0
    assert extraction.supplier_name.confidence == 1.0
