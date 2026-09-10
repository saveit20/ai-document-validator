"""Extractor contract and the deterministic step from raw candidates to typed, scored fields."""

from dataclasses import dataclass
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
    for name in FIELD_NAMES:
        candidate = candidates.get(name, Candidate())
        value = NORMALIZERS[name](candidate.raw) if candidate.raw else None
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
    return Extraction(**fields)
