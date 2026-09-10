"""Extractor contract and the deterministic step from raw candidates to typed, scored fields."""

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from validator import confidence, normalize
from validator.ingest import Document
from validator.models import FIELD_NAMES, Extraction, FieldValue, LLMCallInfo


@dataclass(frozen=True)
class Candidate:
    """What an extractor found for one field, before normalisation."""

    raw: str | None = None
    evidence: str | None = None
    page: int | None = None
    ambiguous: bool = False


@dataclass(frozen=True)
class ExtractorOutput:
    candidates: dict[str, Candidate]
    used: str
    llm: LLMCallInfo | None = None


class Extractor(Protocol):
    def extract(self, document: Document) -> ExtractorOutput: ...


NORMALIZERS = {
    "supplier_name": normalize.normalize_text,
    "invoice_number": normalize.normalize_text,
    "invoice_date": normalize.normalize_date,
    "total_amount": normalize.normalize_amount,
    "currency": normalize.normalize_currency,
    "tax_id": normalize.normalize_tax_id,
    "subtotal_amount": normalize.normalize_amount,
    "tax_amount": normalize.normalize_amount,
    "customer_name": normalize.normalize_text,
    "customer_tax_id": normalize.normalize_tax_id,
}


def build_extraction(candidates: dict[str, Candidate], document: Document) -> Extraction:
    """Normalise every candidate and score it against the document. Same path for all extractors."""
    fields = {}
    order = normalize.date_order(document.text)
    three_decimals = normalize.amount_decimals(document.text) == 3
    credit_note = normalize.is_credit_note(document.text)
    for name in FIELD_NAMES:
        candidate = candidates.get(name, Candidate())
        if not candidate.raw:
            value = None
        elif name == "invoice_date":
            value = normalize.normalize_date(candidate.raw, order)
        elif name in confidence.AMOUNT_FIELDS:
            value = normalize.normalize_amount(candidate.raw, three_decimals)
            if credit_note and value is not None and value > 0:
                # Accounting books a credit note negative, whatever sign it prints.
                value = -value
        else:
            value = NORMALIZERS[name](candidate.raw)
        conf = confidence.score(
            name,
            value,
            raw=candidate.raw,
            evidence=candidate.evidence,
            ambiguous=candidate.ambiguous,
            document_text=document.text,
        )
        evidence = candidate.evidence if candidate.raw else None
        page = candidate.page if candidate.page is not None else document.page_of(evidence)
        fields[name] = FieldValue(value=value, confidence=conf, evidence=evidence, page=page)
    _reconcile_tax(fields)
    _check_roles(fields)
    return Extraction(**fields)


# Labels that introduce the invoice's recipient. Grounding proves a value is printed, not whose it is.
_CUSTOMER_LABEL = re.compile(
    r"\b(bill(?:ed)?\s+to|sold\s+to|ship\s+to|invoice\s+to|customer|client|cliente|buyer|recipient|"
    r"destinatario|destinataire|facturar\s+a|kunde|rechnungsempf[aä]nger)\b",
    re.IGNORECASE,
)


_SUPPLIER_LABEL = re.compile(
    r"\b(from|seller|supplier|vendor|issued\s+by|emisor|proveedor|lieferant|fournisseur|fornitore)\b",
    re.IGNORECASE,
)


def _check_roles(fields: dict[str, FieldValue]) -> None:
    """Doubt a party's name and tax id when they are the other party's, or quoted from the other
    party's block: a value that is printed on the invoice but belongs to the other party is wrong."""
    name, tax_id = fields["supplier_name"], fields["tax_id"]
    customer, customer_tax_id = fields["customer_name"], fields["customer_tax_id"]
    same_party = (
        name.value is not None
        and customer.value is not None
        and normalize.canon(name.value) == normalize.canon(customer.value)
    ) or (
        tax_id.value is not None
        and customer_tax_id.value is not None
        and normalize.same_tax_id(tax_id.value, customer_tax_id.value)
    )
    sides = (
        (("supplier_name", "tax_id"), _CUSTOMER_LABEL),
        (("customer_name", "customer_tax_id"), _SUPPLIER_LABEL),
    )
    for names, other_party_label in sides:
        for field_name in names:
            field = fields[field_name]
            quoted_from_other = bool(field.evidence and other_party_label.search(field.evidence))
            if field.confidence == confidence.HIGH and (same_party or quoted_from_other):
                fields[field_name] = field.model_copy(update={"confidence": confidence.AMBIGUOUS})


def _reconcile_tax(fields: dict[str, FieldValue]) -> None:
    """Confirm an uncertain tax total when verified subtotal and total prove it: subtotal + tax =
    total. This is what makes a tax total summed from per-rate lines fully trusted."""
    tax, subtotal, total = (fields[f] for f in ("tax_amount", "subtotal_amount", "total_amount"))
    if (
        tax.confidence == confidence.AMBIGUOUS
        and subtotal.confidence == confidence.HIGH
        and total.confidence == confidence.HIGH
        and abs(subtotal.value + tax.value - total.value) <= Decimal("0.01")
    ):
        fields["tax_amount"] = tax.model_copy(update={"confidence": confidence.HIGH})
