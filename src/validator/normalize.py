"""Deterministic parsing of raw strings into canonical field values."""

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

DateOrder = Literal["DMY", "MDY"]

# Keys are case-folded and accent-free (see `fold`).
MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9,
    "sep": 9, "sept": 9, "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12,
    "dec": 12,
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "janvier": 1, "janv": 1, "fevrier": 2, "fevr": 2, "mars": 3, "avril": 4, "avr": 4, "mai": 5,
    "juin": 6, "juillet": 7, "juil": 7, "aout": 8, "septembre": 9, "octobre": 10, "decembre": 12,
    "januar": 1, "janner": 1, "februar": 2, "marz": 3, "juni": 6, "juli": 7, "oktober": 10,
    "okt": 10, "dezember": 12, "dez": 12,
    "gennaio": 1, "febbraio": 2, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
    "settembre": 9, "ottobre": 10, "dicembre": 12,
    "janeiro": 1, "fevereiro": 2, "marco": 3, "maio": 5, "junho": 6, "julho": 7, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
    "januari": 1, "februari": 2, "maart": 3, "mei": 5, "augustus": 8,
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5, "czerwca": 6, "lipca": 7,
    "sierpnia": 8, "wrzesnia": 9, "pazdziernika": 10, "listopada": 11, "grudnia": 12,
}  # fmt: skip

_YMD_DATE = re.compile(r"\b(\d{4})([-/.])(\d{1,2})\2(\d{1,2})\b")
_CJK_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
_NUMERIC_DATE = re.compile(r"\b(\d{1,2})([/.\-])(\d{1,2})\2(\d{4}|\d{2})\b")
_DAY_MONTH_YEAR = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th|er|º|\.)?[\s\-]+(?:de\s+)?([^\W\d_]{3,})\.?,?[\s\-]+(?:de\s+)?"
    r"(\d{4}|\d{2})\b"
)
_MONTH_DAY_YEAR = re.compile(r"\b([^\W\d_]{3,})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b")

_US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM",
    "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
    "WV", "WI", "WY",
]  # fmt: skip
_US_ADDRESS = re.compile(rf"\b(?:{'|'.join(_US_STATES)})\s+\d{{5}}(?:-\d{{4}})?\b")

_GROUP_SEPARATORS = "   '’"
_AMOUNT_TOKEN = re.compile(
    rf"-?\d{{1,3}}(?:[{_GROUP_SEPARATORS}]\d{{3}})+(?:[.,]\d{{1,2}})?(?![\d.,])"
    r"|-?\d[\d.,]*\d|-?\d"
)
_DECIMALS = re.compile(r"[.,]\d{2}$")

# Currencies of the main trading economies. ISO codes that are also common words ("ALL", "TOP", "CUP")
# are left out, because a bare three-letter word would otherwise read as a currency.
ISO_CURRENCIES = frozenset([
    "EUR", "GBP", "USD", "CHF", "SEK", "NOK", "DKK", "ISK", "PLN", "CZK", "HUF", "RON", "BGN", "RSD",
    "UAH", "RUB", "TRY", "ILS", "AED", "SAR", "QAR", "KWD", "BHD", "OMR", "EGP", "MAD", "NGN", "KES",
    "ZAR", "INR", "PKR", "BDT", "LKR", "CNY", "HKD", "TWD", "JPY", "KRW", "SGD", "MYR", "THB", "IDR",
    "PHP", "VND", "AUD", "NZD", "CAD", "MXN", "BRL", "ARS", "CLP", "COP", "PEN", "UYU",
])  # fmt: skip
_CURRENCY_CODE = re.compile(r"\b[A-Z]{3}\b")
# (symbol, ISO code, ambiguous). Letter-prefixed dollars must be tried before the bare "$".
_SYMBOLS = [
    ("US$", "USD", False), ("AU$", "AUD", False), ("CA$", "CAD", False), ("NZ$", "NZD", False),
    ("HK$", "HKD", False), ("MX$", "MXN", False), ("NT$", "TWD", False), ("A$", "AUD", False),
    ("C$", "CAD", False), ("S$", "SGD", False), ("R$", "BRL", False), ("$", "USD", True),
    ("€", "EUR", False), ("£", "GBP", False), ("₹", "INR", False), ("₩", "KRW", False),
    ("₺", "TRY", False), ("₽", "RUB", False), ("₪", "ILS", False), ("₫", "VND", False),
    ("฿", "THB", False), ("¥", "JPY", True),
]  # fmt: skip
_SYMBOL_PATTERN = re.compile("|".join(re.escape(symbol) for symbol, _, _ in _SYMBOLS))
_SYMBOL_CODES = {symbol: (code, ambiguous) for symbol, code, ambiguous in _SYMBOLS}
# Written abbreviations and names; "kr" is shared by SEK, NOK, DKK and ISK.
_CURRENCY_WORDS = [
    (re.compile(r"(?<![^\W\d_])(?:zł|złotych|złoty|zloty)(?![^\W\d_])", re.I), "PLN", False),
    (re.compile(r"(?<![^\W\d_])Kč(?![^\W\d_])"), "CZK", False),
    (re.compile(r"(?<![^\W\d_])(?:Ft|forint)(?![^\W\d_])"), "HUF", False),
    (re.compile(r"(?<![^\W\d_])kr\.?(?![^\W\d_])"), "SEK", True),
    (re.compile(r"(?<![^\W\d_])S?Fr\.(?!\w)"), "CHF", False),
    (re.compile(r"\b(?:swiss francs?|francs? suisses?|schweizer franken)\b", re.I), "CHF", False),
    (re.compile(r"\beuros?\b", re.I), "EUR", False),
    (re.compile(r"\bpounds? sterling\b", re.I), "GBP", False),
    (re.compile(r"\bus dollars?\b", re.I), "USD", False),
    (re.compile(r"\brupees?\b", re.I), "INR", False),
    (re.compile(r"\byen\b", re.I), "JPY", False),
]

_VAT_PREFIXES = frozenset([
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "GB", "HR", "HU", "IE",
    "IT", "LT", "LU", "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK", "XI", "CH", "NO",
])  # fmt: skip
_EU_VAT_ID = re.compile(
    rf"\b(?:{'|'.join(sorted(_VAT_PREFIXES - {'CH', 'NO'}))})[ ]?(?=[0-9A-Z]*\d{{6}})[0-9A-Z]{{8,12}}\b"
)
_SPANISH_ID = re.compile(r"^(?:[A-Z]\d{7}[A-Z0-9]|\d{8}[A-Z])$")


def fold(text: str) -> str:
    """Case-folded text without accents: 'MärZ' -> 'marz'."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _safe_date(year: int, month: int, day: int) -> date | None:
    if year < 100:
        year += 2000 if year < 70 else 1900
    try:
        return date(year, month, day)
    except ValueError:
        return None


def date_readings(text: str) -> list[tuple[str, tuple[date, ...]]]:
    """Every date in `text`, in order, as (matched text, valid readings).

    A numeric date such as 04/08/2026 has two readings, day-first then month-first; every other
    form has one. Invalid readings are dropped, and dates with none are skipped.
    """
    found: list[tuple[int, str, tuple[date | None, ...]]] = []
    for m in _YMD_DATE.finditer(text):
        found.append((m.start(), m[0], (_safe_date(int(m[1]), int(m[3]), int(m[4])),)))
    for m in _CJK_DATE.finditer(text):
        found.append((m.start(), m[0], (_safe_date(int(m[1]), int(m[2]), int(m[3])),)))
    for m in _NUMERIC_DATE.finditer(text):
        if m[2] == "-" and len(m[4]) == 2:
            continue
        first, second, year = int(m[1]), int(m[3]), int(m[4])
        found.append(
            (m.start(), m[0], (_safe_date(year, second, first), _safe_date(year, first, second)))
        )
    for m in _DAY_MONTH_YEAR.finditer(text):
        if month := MONTHS.get(fold(m[2])):
            found.append((m.start(), m[0], (_safe_date(int(m[3]), month, int(m[1])),)))
    for m in _MONTH_DAY_YEAR.finditer(text):
        if month := MONTHS.get(fold(m[1])):
            found.append((m.start(), m[0], (_safe_date(int(m[3]), month, int(m[2])),)))
    readings = []
    for _, matched, options in sorted(found, key=lambda item: item[0]):
        valid = tuple(dict.fromkeys(d for d in options if d is not None))
        if valid:
            readings.append((matched, valid))
    return readings


def pick_reading(readings: tuple[date, ...], order: DateOrder | None) -> date:
    """Day-first unless the document is month-first (ASSUMPTION-09)."""
    return readings[-1] if order == "MDY" else readings[0]


def date_order(text: str) -> DateOrder | None:
    """The document's numeric date convention, or None when nothing in it decides.

    An unambiguous numeric date (a component above 12) decides first. Otherwise the issuer's
    country decides: a US postal address means month-first; a euro or pound sign or an EU VAT
    number means day-first. Conflicting or absent signals give None.
    """
    day_first = month_first = False
    for m in _NUMERIC_DATE.finditer(text):
        first, second = int(m[1]), int(m[3])
        day_first |= first > 12 >= second
        month_first |= second > 12 >= first
    if day_first != month_first:
        return "DMY" if day_first else "MDY"
    if day_first and month_first:
        return None
    us, european = _country_signals(text)
    if us != european:
        return "MDY" if us else "DMY"
    return None


def _country_signals(text: str) -> tuple[bool, bool]:
    """(has a US postal address, has a euro or pound sign or an EU VAT number)."""
    european = "€" in text or "£" in text or bool(_EU_VAT_ID.search(text))
    return bool(_US_ADDRESS.search(text)), european


def local_dollar(text: str) -> str | None:
    """What a bare '$' means in this document: USD when the only country signal is a US address."""
    us, european = _country_signals(text)
    return "USD" if us and not european else None


def find_dates(text: str, order: DateOrder | None = None) -> list[tuple[date, str, bool]]:
    """All dates in `text` as (date, matched text, ambiguous), read in the given order.

    Without an order, a numeric date that reads both ways is day-first and flagged ambiguous.
    """
    return [
        (pick_reading(readings, order), matched, order is None and len(readings) > 1)
        for matched, readings in date_readings(text)
    ]


def normalize_date(raw: str | None, order: DateOrder | None = None) -> date | None:
    if not raw:
        return None
    found = find_dates(raw, order)
    return found[0][0] if found else None


def parse_amount(token: str) -> tuple[Decimal, bool] | None:
    """Parse one numeric token into (value, ambiguous).

    Spaces and apostrophes are thousands separators. A single '.' or ',' followed by exactly three
    digits ('1.500', '1,500') can be a thousands or a decimal separator; it is read as thousands
    and flagged as ambiguous.
    """
    negative = token.startswith("-")
    digits = re.sub(f"[{_GROUP_SEPARATORS}]", "", token.lstrip("-"))
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

    Skips numbers glued to letters (postcodes, item codes such as 'M12') and percentages. Reads
    accounting negatives: '(1,234.56)' and a trailing minus as in '1.234,56-'.
    """
    text = text.replace("−", "-")
    amounts = []
    for m in _AMOUNT_TOKEN.finditer(text):
        start, end = m.span()
        token = m[0]
        if start > 0 and text[start - 1].isalnum():
            continue
        if end < len(text) and (text[end].isalpha() or text[end] == "%"):
            continue
        if not (parsed := parse_amount(token)):
            continue
        value, ambiguous = parsed
        has_decimals = bool(_DECIMALS.search(token))
        after = text[end : end + 2]
        in_parentheses = start > 0 and text[start - 1] == "(" and after[:1] == ")"
        trailing_minus = after[:1] == "-" and not after[1:2].isdigit()
        if has_decimals and value > 0 and in_parentheses:
            value, token = -value, text[start - 1 : end + 1]
        elif has_decimals and value > 0 and trailing_minus:
            value, token = -value, text[start : end + 1]
        amounts.append((value, ambiguous, token))
    return amounts


def normalize_amount(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    amounts = find_amounts(raw)
    return amounts[-1][0] if amounts else None


def find_currencies(text: str) -> list[tuple[str, bool, str]]:
    """Currencies in `text` as (ISO code, ambiguous, matched text): codes, symbols, then names.

    '$', '¥' and 'kr' are shared by several currencies and are flagged as ambiguous.
    """
    found = [(m[0], False, m[0]) for m in _CURRENCY_CODE.finditer(text) if m[0] in ISO_CURRENCIES]
    for m in _SYMBOL_PATTERN.finditer(text):
        code, ambiguous = _SYMBOL_CODES[m[0]]
        found.append((code, ambiguous, m[0]))
    for pattern, code, ambiguous in _CURRENCY_WORDS:
        found += [(code, ambiguous, m[0]) for m in pattern.finditer(text)]
    return found


def normalize_currency(raw: str | None) -> str | None:
    if not raw:
        return None
    found = find_currencies(raw) or find_currencies(raw.upper())
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
    """Letters and digits of any script, case- and accent-folded; compares a value with evidence."""
    return "".join(ch for ch in fold(text) if ch.isalnum())


def squash(text: str) -> str:
    """Case-folded text with collapsed whitespace; locates evidence inside a document."""
    return " ".join(text.casefold().split())
