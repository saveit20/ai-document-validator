"""Heuristic: labels in several languages, and values the text layer printed apart from their label."""

from datetime import date
from decimal import Decimal

import pytest

from validator.extraction import build_extraction
from validator.heuristic import HeuristicExtractor
from validator.ingest import document_from_text


def extract(text: str):
    document = document_from_text(text)
    return build_extraction(HeuristicExtractor().extract(document).candidates, document)


@pytest.mark.parametrize(
    ("text", "total"),
    [
        ("Nettobetrag 100,00\n19 % MwSt. 19,00\nGesamtbetrag 119,00 EUR\n", "119.00"),
        ("Imponibile 100,00\nIVA 22% 22,00\nTotale documento 122,00 EUR\n", "122.00"),
        ("Subtotaal 100,00\nBTW 21% 21,00\nTotaal te betalen 121,00 EUR\n", "121.00"),
        ("Zwischensumme 100.00\nMWST 8.1% 8.10\nRechnungstotal 108.10 CHF\n", "108.10"),
        ("Total HT 500,00 EUR\nTVA 20 % 100,00 EUR\nTotal TTC 600,00 EUR\n", "600.00"),
    ],
)
def test_total_labels_in_several_languages(text: str, total: str) -> None:
    assert extract(text).total_amount.value == Decimal(total)


def test_net_total_is_not_the_total() -> None:
    assert extract("Total HT 500,00 EUR\nTVA 20 % 100,00 EUR\n").total_amount.value != Decimal(
        "500.00"
    )


def test_french_net_and_tax_labels() -> None:
    extraction = extract("Total HT 500,00 EUR\nTVA 20 % 100,00 EUR\nTotal TTC 600,00 EUR\n")
    assert extraction.subtotal_amount.value == Decimal("500.00")
    assert extraction.tax_amount.value == Decimal("100.00")


def test_tax_label_after_the_rate() -> None:
    extraction = extract("Netto 100,00\nzzgl. 19 % MwSt. 19,00\nGesamt 119,00 EUR\n")
    assert extraction.tax_amount.value == Decimal("19.00")


def test_value_on_the_line_after_its_label() -> None:
    extraction = extract("Invoice date: 2026-06-01\nTotal\n121.00 EUR\n")
    assert (extraction.total_amount.value, extraction.total_amount.confidence) == (
        Decimal("121.00"),
        1.0,
    )


def test_table_printed_as_labels_then_values() -> None:
    extraction = extract("SUMMARY\nNet amount\nVAT\nTotal amount\n20,00\n2,00\n22,00\n")
    assert extraction.subtotal_amount.value == Decimal("20.00")
    assert extraction.tax_amount.value == Decimal("2.00")
    assert extraction.total_amount.value == Decimal("22.00")


def test_a_label_followed_by_several_values_is_left_alone() -> None:
    assert extract("Total\n$ 20,00\n$ 2,00\n$ 22,00\n").total_amount.value is None


@pytest.mark.parametrize(
    ("line", "number"),
    [
        ("Rechnungsnummer: 2026-0042", "2026-0042"),
        ("Rechnungs-Nr.: RE-778", "RE-778"),
        ("Facture n° : F-2026-17", "F-2026-17"),
        ("Fattura n. 45/2026", "45/2026"),
        ("Factuurnummer 2026-100", "2026-100"),
        ("Numer faktury: FV/12/2026", "FV/12/2026"),
        ("Invoice: INV-42", "INV-42"),
        ("FACTURA Nº Factura: FV-2026/0417", "FV-2026/0417"),
    ],
)
def test_invoice_number_labels(line: str, number: str) -> None:
    assert extract(f"{line}\nTotal 10.00 EUR\n").invoice_number.value == number


def test_date_on_the_line_after_its_label_is_fully_confident() -> None:
    text = "Seller:\nJones and Sons\nLake Brendaville, NV 53065\nDate of issue:\n04/08/2012\n"
    extraction = extract(text + "Due date:\n05/08/2012\n")
    assert (extraction.invoice_date.value, extraction.invoice_date.confidence) == (
        date(2012, 4, 8),
        1.0,
    )


def test_customer_block_keeps_the_customer_tax_id_on_its_fifth_line() -> None:
    text = (
        "Seller:\nJones and Sons\nTax Id: 964-77-0583\n"
        "Client:\nJenkins, Cobb and Woods\n04886 Hansen Meadows\nSouth Alisonstad, CO 58240\n"
        "Tax Id: 951-94-9050\nITEMS\n"
    )
    extraction = extract(text)
    assert (extraction.tax_id.value, extraction.tax_id.confidence) == ("964770583", 1.0)
    assert extraction.customer_tax_id.value == "951949050"


def test_invoice_number_needs_a_digit() -> None:
    text = "Please quote the invoice number with your payment.\nTotal 10.00 EUR\n"
    assert extract(text).invoice_number.value is None
