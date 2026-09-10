from datetime import date
from decimal import Decimal

import pytest

from validator import normalize as n


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-06-15", date(2026, 6, 15)),
        ("03/06/2026", date(2026, 6, 3)),
        ("15 May 2026", date(2026, 5, 15)),
        ("June 20, 2026", date(2026, 6, 20)),
        ("3 de junio de 2026", date(2026, 6, 3)),
        ("Date of issue: 10 January 2026", date(2026, 1, 10)),
    ],
)
def test_normalize_date_formats(raw: str, expected: date) -> None:
    assert n.normalize_date(raw) == expected


@pytest.mark.parametrize(
    "raw", ["INV-2026-0142", "2026/0381", "31/02/2026", "Unit 7, Riverside", ""]
)
def test_normalize_date_rejects_non_dates(raw: str) -> None:
    assert n.normalize_date(raw) is None


@pytest.mark.parametrize(
    ("token", "value", "ambiguous"),
    [
        ("1,250.00", "1250.00", False),
        ("1.234,56", "1234.56", False),
        ("214,26", "214.26", False),
        ("-150,00", "-150.00", False),
        ("1.500", "1500", True),
        ("1,500", "1500", True),
        ("1.234.567", "1234567", False),
        ("650.00", "650.00", False),
        ("7800", "7800", False),
    ],
)
def test_parse_amount(token: str, value: str, ambiguous: bool) -> None:
    assert n.parse_amount(token) == (Decimal(value), ambiguous)


@pytest.mark.parametrize("token", ["1.23456", "12.3.4"])
def test_parse_amount_rejects_malformed(token: str) -> None:
    assert n.parse_amount(token) is None


def test_find_amounts_skips_percentages_and_codes() -> None:
    found = n.find_amounts("VAT (21%) on item M12: 714.00 EUR")
    assert [amount for amount, _, _ in found] == [Decimal("714.00")]


def test_normalize_amount_takes_last_number() -> None:
    assert n.normalize_amount("Total Due: $2,600.00 USD") == Decimal("2600.00")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("EUR", "EUR"),
        ("1.234,56 €", "EUR"),
        ("£2,400.00", "GBP"),
        ("$2,600.00 USD", "USD"),
        ("VAT NIF IVA", None),
    ],
)
def test_normalize_currency(raw: str, expected: str | None) -> None:
    assert n.normalize_currency(raw) == expected


def test_dollar_sign_alone_is_ambiguous() -> None:
    assert n.find_currencies("$120.00") == [("USD", True, "$")]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("GB 987 6543 21", "GB987654321"),
        ("B-87654321", "B87654321"),
        ("NL853746214B01", "NL853746214B01"),
        ("94-3175623", "943175623"),
        ("20% 200.00", None),
        ("(21%): 714.00 EUR", None),
    ],
)
def test_normalize_tax_id(raw: str, expected: str | None) -> None:
    assert n.normalize_tax_id(raw) == expected


def test_normalize_text_collapses_whitespace() -> None:
    assert n.normalize_text("  ACME   Supplies Ltd ") == "ACME Supplies Ltd"
    assert n.normalize_text("   ") is None


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("ESB12345678", "B12345678", True),
        ("B12345678", "B12345678", True),
        ("GB123456789", "B12345678", False),
        ("ESB12345678", "A46987654", False),
    ],
)
def test_same_tax_id(a: str, b: str, same: bool) -> None:
    assert n.same_tax_id(a, b) is same
