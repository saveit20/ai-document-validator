"""Per-field confidence computed from verifiable signals, never from model self-assessment.

1.0  normalised, evidence found verbatim in the document, no competing candidates
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

_AMOUNT_FIELDS = frozenset({"total_amount", "subtotal_amount", "tax_amount"})


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
    if not evidence or normalize.squash(evidence) not in normalize.squash(document_text):
        return UNGROUNDED
    supported, format_ambiguous = supports(field, value, evidence)
    if not supported:
        return UNGROUNDED
    if ambiguous or format_ambiguous:
        return AMBIGUOUS
    return HIGH


def supports(field: str, value: Any, evidence: str) -> tuple[bool, bool]:
    """Whether `evidence` really contains `value`, and whether that reading is ambiguous."""
    if field == "invoice_date":
        return any(found == value for found, _ in normalize.find_dates(evidence)), False
    if field in _AMOUNT_FIELDS:
        flags = [amb for amount, amb, _ in normalize.find_amounts(evidence) if amount == value]
        return bool(flags), bool(flags) and all(flags)
    if field == "currency":
        flags = [amb for code, amb, _ in normalize.find_currencies(evidence) if code == value]
        return bool(flags), bool(flags) and all(flags)
    return normalize.canon(str(value)) in normalize.canon(evidence), False
