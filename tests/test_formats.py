"""Country and format robustness: grouped and negative amounts, date order, currencies, grounding."""

from datetime import date
from decimal import Decimal

import pytest

from validator import confidence
from validator import normalize as n
from validator.extraction import Candidate, build_extraction
from validator.heuristic import HeuristicExtractor
from validator.ingest import document_from_text

US_SELLER = "Seller: Jones and Sons\nLake Brendaville, NV 53065\n"
ES_SELLER = "Emisor: Hormigones del Sur S.L.\nNIF: ESB12345678\n"


def heuristic(text: str):
    document = document_from_text(text)
    return build_extraction(HeuristicExtractor().extract(document).candidates, document)


def llm_field(field: str, raw: str, evidence: str, text: str):
    document = document_from_text(text)
    return build_extraction({field: Candidate(raw=raw, evidence=evidence)}, document).field(field)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1 234,56", "1234.56"),
        ("1 234,56", "1234.56"),
        ("1 234,56", "1234.56"),
        ("1'234.50", "1234.50"),
        ("1’234.50", "1234.50"),
        ("12 345 678,90", "12345678.90"),
    ],
)
def test_grouped_amounts_are_read_whole(raw: str, expected: str) -> None:
    assert n.normalize_amount(raw) == Decimal(expected)


def test_amount_groups_do_not_join_across_lines() -> None:
    assert [a for a, _, _ in n.find_amounts("1.\n 2,00\n each")] == [Decimal("1"), Decimal("2.00")]


def test_heuristic_total_with_apostrophe_grouping() -> None:
    extraction = heuristic("Subtotal 7'000.00\nVAT 8.1% 567.00\nTotal 7'567.00 CHF\n")
    assert extraction.total_amount.value == Decimal("7567.00")


def test_llm_amount_is_supported_by_space_grouped_evidence() -> None:
    field = llm_field(
        "total_amount",
        "2400.00",
        "Montant total TTC 2 400,00 EUR",
        "Montant total TTC 2 400,00 EUR\n",
    )
    assert (field.value, field.confidence) == (Decimal("2400.00"), 1.0)


@pytest.mark.parametrize("raw", ["(1,234.56)", "1,234.56-", "1.234,56-", "-1 234,56"])
def test_accounting_negative_notations_keep_the_sign(raw: str) -> None:
    assert n.normalize_amount(raw) == Decimal("-1234.56")


def test_parentheses_without_decimals_are_not_negative() -> None:
    assert [a for a, _, _ in n.find_amounts("Tel (555) 010")] == [Decimal("555"), Decimal("10")]


def test_heuristic_credit_note_total_is_negative() -> None:
    assert heuristic("CREDIT NOTE\nTotal due (250.00) GBP\n").total_amount.value == Decimal(
        "-250.00"
    )


def test_only_valid_reading_of_a_numeric_date_is_taken() -> None:
    assert n.normalize_date("04/13/2026") == date(2026, 4, 13)


@pytest.mark.parametrize(
    ("text", "order"),
    [
        ("Invoice date: 04/08/2026\nDue date: 05/23/2026", "MDY"),
        ("Fecha: 04/08/2026\nVencimiento: 23/05/2026", "DMY"),
        (US_SELLER + "Date: 04/08/2026", "MDY"),
        (ES_SELLER + "Fecha: 04/08/2026", "DMY"),
        ("Total 121,00 €\nDate: 04/08/2026", "DMY"),
        ("Date: 04/08/2026", None),
        (US_SELLER + ES_SELLER + "Date: 04/08/2026", None),
    ],
)
def test_document_date_order(text: str, order: str | None) -> None:
    assert n.date_order(text) == order


def test_heuristic_reads_month_first_when_the_document_says_so() -> None:
    extraction = heuristic("Invoice date: 04/08/2026\nDue date: 05/23/2026\nTotal 10.00 USD\n")
    assert (extraction.invoice_date.value, extraction.invoice_date.confidence) == (
        date(2026, 4, 8),
        1.0,
    )


def test_ambiguous_numeric_date_without_signal_is_not_fully_confident() -> None:
    assert heuristic("Invoice date: 04/08/2026\nTotal 10.00\n").invoice_date.confidence < 1.0


def test_european_document_keeps_confident_day_first_dates() -> None:
    extraction = heuristic(ES_SELLER + "Fecha de factura: 03/06/2026\nTotal 121,00 EUR\n")
    assert (extraction.invoice_date.value, extraction.invoice_date.confidence) == (
        date(2026, 6, 3),
        1.0,
    )


@pytest.mark.parametrize(
    ("text", "expected_confidence"),
    [(US_SELLER + "Date of issue: 04/08/2012\n", 1.0), ("Date of issue: 04/08/2012\n", 0.6)],
)
def test_llm_month_first_date_confidence_depends_on_document_signals(
    text: str, expected_confidence: float
) -> None:
    field = llm_field("invoice_date", "2012-04-08", "Date of issue: 04/08/2012", text)
    assert (field.value, field.confidence) == (date(2012, 4, 8), expected_confidence)


def test_supports_reports_an_ambiguous_numeric_date() -> None:
    assert confidence.supports("invoice_date", date(2026, 8, 4), "Date: 04/08/2026") == (True, True)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("15. März 2026", date(2026, 3, 15)),
        ("1er mars 2026", date(2026, 3, 1)),
        ("3 août 2026", date(2026, 8, 3)),
        ("15 févr. 2026", date(2026, 2, 15)),
        ("3 ottobre 2026", date(2026, 10, 3)),
        ("15 de março de 2026", date(2026, 3, 15)),
        ("15 maart 2026", date(2026, 3, 15)),
        ("15 marca 2026", date(2026, 3, 15)),
        ("15-Mar-2026", date(2026, 3, 15)),
        ("15-Mar-26", date(2026, 3, 15)),
        ("2026/05/12", date(2026, 5, 12)),
        ("2026.05.12", date(2026, 5, 12)),
        ("12.05.26", date(2026, 5, 12)),
        ("2026年5月12日", date(2026, 5, 12)),
    ],
)
def test_date_formats_across_countries(raw: str, expected: date) -> None:
    assert n.normalize_date(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("INR", "INR"),
        ("SGD", "SGD"),
        ("ZAR", "ZAR"),
        ("usd", "USD"),
        ("A$ 100", "AUD"),
        ("C$ 100", "CAD"),
        ("R$ 100", "BRL"),
        ("HK$ 100", "HKD"),
        ("100 zł", "PLN"),
        ("100 Kč", "CZK"),
        ("100 Ft", "HUF"),
        ("₹100", "INR"),
        ("Fr. 100", "CHF"),
        ("Swiss francs", "CHF"),
        ("euros", "EUR"),
    ],
)
def test_currency_forms(raw: str, expected: str) -> None:
    assert n.normalize_currency(raw) == expected


def test_prefixed_dollar_is_not_a_us_dollar() -> None:
    assert "USD" not in {code for code, _, _ in n.find_currencies("Total A$ 110.00")}


@pytest.mark.parametrize("text", ["Totalt 1 250,00 kr", "合計 ¥12,000"])
def test_symbols_shared_by_several_currencies_are_ambiguous(text: str) -> None:
    found = n.find_currencies(text)
    assert found and all(ambiguous for _, ambiguous, _ in found)


@pytest.mark.parametrize(
    ("text", "expected_confidence"),
    [(US_SELLER + "Total $ 22,00\n", 1.0), ("Total $ 22,00\n", 0.6)],
)
def test_bare_dollar_is_resolved_by_a_us_address(text: str, expected_confidence: float) -> None:
    assert llm_field("currency", "USD", "Total $ 22,00", text).confidence == expected_confidence


def test_non_latin_value_is_not_trivially_supported() -> None:
    text = "Προμηθευτής: Άλφα ΑΕ\nTotal 100.00 EUR\n"
    field = llm_field("supplier_name", "Ωμέγα ΑΕ", "Total 100.00 EUR", text)
    assert field.confidence < 1.0


def test_evidence_spanning_lines_that_the_text_layer_separates_is_grounded() -> None:
    text = "SUMMARY\nNet worth\nVAT\n10%\n20,00\n2,00\nTotal\n$ 22,00\n"
    field = llm_field("subtotal_amount", "20.00", "Net worth\n20,00", text)
    assert field.confidence == 1.0


def test_evidence_with_a_line_missing_from_the_document_is_not_grounded() -> None:
    text = "SUMMARY\nNet worth\n20,00\n"
    field = llm_field("subtotal_amount", "20.00", "Net amount\n20,00", text)
    assert field.confidence == 0.3


@pytest.mark.parametrize(
    ("text", "decimals"), [("Total KWD 46.500", 3), ("Total 46.500 BHD", 3), ("Total EUR 1.500", 2)]
)
def test_documents_in_three_decimal_currencies_are_detected(text: str, decimals: int) -> None:
    assert n.amount_decimals(text) == decimals


def test_three_decimal_currency_reads_a_dot_as_the_decimal_separator() -> None:
    assert n.normalize_amount("46.500", three_decimals=True) == Decimal("46.500")
    assert n.normalize_amount("1,250.500", three_decimals=True) == Decimal("1250.500")
    assert n.normalize_amount("1,500", three_decimals=True) == Decimal("1500")


def test_kuwaiti_dinar_total_is_read_and_confirmed() -> None:
    field = llm_field("total_amount", "46.500", "Total KWD 46.500", "Total KWD 46.500\n")
    assert (field.value, field.confidence) == (Decimal("46.500"), 1.0)
