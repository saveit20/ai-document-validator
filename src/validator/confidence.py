"""Per-field confidence computed from verifiable signals, never from model self-assessment.

1.0  normalised, evidence found in the document, no competing candidates
0.6  grounded but ambiguous: competing candidates or an ambiguous format such as '1.500'
0.3  not grounded in the document, or found but not parseable
0.0  not found
"""

from typing import Any

from validator import normalize

HIGH = 1.0
AMBIGUOUS = 0.6
UNGROUNDED = 0.3
MISSING = 0.0

AMOUNT_FIELDS = frozenset({"total_amount", "subtotal_amount", "tax_amount"})


def score(
    field: str,
    value: Any,
    *,
    raw: str | None,
    evidence: str | None,
    ambiguous: bool,
    document_text: str,
) -> float:
    if value is None:
        return UNGROUNDED if raw else MISSING
    if not evidence or not grounded(evidence, document_text):
        return UNGROUNDED
    supported, format_ambiguous = supports(field, value, evidence, document_text)
    if not supported:
        return UNGROUNDED
    if ambiguous or format_ambiguous:
        return AMBIGUOUS
    return HIGH


def grounded(evidence: str, document_text: str) -> bool:
    """Evidence appears in the document verbatim, or line by line.

    PDF text layers often emit table columns or two-column headers as separate runs, so a label
    and its value that sit side by side on the page are not adjacent in the text. Evidence that
    spans several lines is accepted when every one of its lines is in the document.
    """
    document = normalize.squash(document_text)
    if normalize.squash(evidence) in document:
        return True
    lines = [normalize.squash(line) for line in evidence.splitlines() if line.strip()]
    return len(lines) > 1 and all(line in document for line in lines)


def supports(field: str, value: Any, evidence: str, document_text: str = "") -> tuple[bool, bool]:
    """Whether `evidence` really contains `value`, and whether that reading is ambiguous."""
    if field == "invoice_date":
        order = normalize.date_order(document_text)
        for _, readings in normalize.date_readings(evidence):
            if order is None and value in readings:
                return True, len(readings) > 1
            if order is not None and value == normalize.pick_reading(readings, order):
                return True, False
        return False, False
    if field in AMOUNT_FIELDS:
        three_decimals = normalize.amount_decimals(document_text) == 3
        amounts = normalize.find_amounts(evidence, three_decimals)
        flags = [amb for amount, amb, _ in amounts if amount == value]
        return bool(flags), bool(flags) and all(flags)
    if field == "currency":
        flags = [amb for code, amb, _ in normalize.find_currencies(evidence) if code == value]
        resolved = value == normalize.local_dollar(document_text)
        return bool(flags), bool(flags) and all(flags) and not resolved
    expected = normalize.canon(str(value))
    return bool(expected) and expected in normalize.canon(evidence), False
