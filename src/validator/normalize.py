"""Deterministic parsing of raw strings into canonical field values."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9,
    "sep": 9, "sept": 9, "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12,
    "dec": 12, "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11,
    "diciembre": 12,
}  # fmt: skip

_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})\b")
_DAY_MONTH_YEAR = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:de\s+)?([A-Za-zÀ-ÿ]{3,})\.?,?\s+(?:de\s+)?(\d{4})\b", re.I
)
_MONTH_DAY_YEAR = re.compile(r"\b([A-Za-z]{3,})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")

_AMOUNT_TOKEN = re.compile(r"-?\d[\d.,]*\d|-?\d")

ISO_CURRENCIES = frozenset(
    [
        "EUR",
        "GBP",
        "USD",
        "CHF",
        "SEK",
        "NOK",
        "DKK",
        "PLN",
        "CZK",
        "HUF",
        "RON",
        "CAD",
        "AUD",
        "JPY",
        "CNY",
        "MXN",
        "BRL",
    ]
)
SYMBOLS = {"€": "EUR", "£": "GBP", "$": "USD"}
_CURRENCY_CODE = re.compile(r"\b[A-Z]{3}\b")

_VAT_PREFIXES = frozenset(
    [
        "AT",
        "BE",
        "BG",
        "CY",
        "CZ",
        "DE",
        "DK",
        "EE",
        "EL",
        "ES",
        "FI",
        "FR",
        "GB",
        "HR",
        "HU",
        "IE",
        "IT",
        "LT",
        "LU",
        "LV",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SE",
        "SI",
        "SK",
        "XI",
        "CH",
        "NO",
    ]
)
_SPANISH_ID = re.compile(r"^(?:[A-Z]\d{7}[A-Z0-9]|\d{8}[A-Z])$")


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def find_dates(text: str) -> list[tuple[date, str]]:
    """All valid dates in `text`, in order of appearance, with the matched substring.

    Numeric dates are read day-first (ASSUMPTION-09).
    """
    found: list[tuple[int, date | None, str]] = []
    for m in _ISO_DATE.finditer(text):
        found.append((m.start(), _safe_date(int(m[1]), int(m[2]), int(m[3])), m[0]))
    for m in _NUMERIC_DATE.finditer(text):
        found.append((m.start(), _safe_date(int(m[3]), int(m[2]), int(m[1])), m[0]))
    for m in _DAY_MONTH_YEAR.finditer(text):
        if month := MONTHS.get(m[2].lower()):
            found.append((m.start(), _safe_date(int(m[3]), month, int(m[1])), m[0]))
    for m in _MONTH_DAY_YEAR.finditer(text):
        if month := MONTHS.get(m[1].lower()):
            found.append((m.start(), _safe_date(int(m[3]), month, int(m[2])), m[0]))
    return [(d, s) for _, d, s in sorted(found, key=lambda item: item[0]) if d is not None]


def normalize_date(raw: str | None) -> date | None:
    if not raw:
        return None
    found = find_dates(raw)
    return found[0][0] if found else None


def parse_amount(token: str) -> tuple[Decimal, bool] | None:
    """Parse one numeric token into (value, ambiguous).

    A single separator followed by exactly three digits ('1.500', '1,500') can be a thousands or a
    decimal separator; it is read as thousands and flagged as ambiguous.
    """
    negative = token.startswith("-")
    digits = token.lstrip("-")
    ambiguous = False
    if "." in digits and "," in digits:
        decimal_sep = "." if digits.rfind(".") > digits.rfind(",") else ","
        thousands_sep = "," if decimal_sep == "." else "."
        digits = digits.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif "." in digits or "," in digits:
        sep = "." if "." in digits else ","
        tails = digits.split(sep)[1:]
        if len(tails) > 1:
            if any(len(tail) != 3 for tail in tails):
                return None
            digits = digits.replace(sep, "")
        elif len(tails[0]) == 3:
            digits = digits.replace(sep, "")
            ambiguous = True
        elif len(tails[0]) in (1, 2):
            digits = digits.replace(sep, ".")
        else:
            return None
    try:
        value = Decimal(digits)
    except InvalidOperation:
        return None
    return (-value if negative else value), ambiguous


def find_amounts(text: str) -> list[tuple[Decimal, bool, str]]:
    """Numeric amounts in `text` as (value, ambiguous, token).

    Skips numbers glued to letters (postcodes, item codes such as 'M12') and percentages.
    """
    text = text.replace("\u2212", "-")
    amounts = []
    for m in _AMOUNT_TOKEN.finditer(text):
        start, end = m.span()
        if start > 0 and text[start - 1].isalnum():
            continue
        if end < len(text) and (text[end].isalpha() or text[end] == "%"):
            continue
        if parsed := parse_amount(m[0]):
            amounts.append((parsed[0], parsed[1], m[0]))
    return amounts


def normalize_amount(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    amounts = find_amounts(raw)
    return amounts[-1][0] if amounts else None


def find_currencies(text: str) -> list[tuple[str, bool, str]]:
    """Currencies in `text` as (ISO code, ambiguous, matched text). '$' alone is ambiguous."""
    found = [(m[0], False, m[0]) for m in _CURRENCY_CODE.finditer(text) if m[0] in ISO_CURRENCIES]
    found += [(code, symbol == "$", symbol) for symbol, code in SYMBOLS.items() if symbol in text]
    return found


def normalize_currency(raw: str | None) -> str | None:
    if not raw:
        return None
    found = find_currencies(raw.upper())
    return found[0][0] if found else None


def normalize_tax_id(raw: str | None) -> str | None:
    """Canonical tax id (upper case, no spaces, dots or hyphens) if it looks like one."""
    if not raw:
        return None
    compact = re.sub(r"[\s.\-]", "", raw.upper())
    match = re.match(r"[A-Z0-9]+", compact)
    if not match:
        return None
    candidate = match[0]
    if candidate[:2] in _VAT_PREFIXES and 8 <= len(candidate) - 2 <= 12:
        return candidate
    if _SPANISH_ID.match(candidate) or re.fullmatch(r"\d{9}", candidate):
        return candidate
    return None


def same_tax_id(a: str, b: str) -> bool:
    """Equal tax ids, allowing one to carry the EU VAT country prefix (ESB12345678 == B12345678)."""
    if a == b:
        return True
    longer, shorter = (a, b) if len(a) > len(b) else (b, a)
    return longer[:2] in _VAT_PREFIXES and longer[2:] == shorter


def normalize_text(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = " ".join(raw.split()).strip(" :;,")
    return cleaned or None


def canon(text: str) -> str:
    """Lower-case alphanumerics only; compares a value with the evidence that should contain it."""
    return re.sub(r"[^0-9a-z]", "", text.casefold())


def squash(text: str) -> str:
    """Case-folded text with collapsed whitespace; locates evidence inside a document."""
    return " ".join(text.casefold().split())
