"""Cascade: run the free heuristic first and call the LLM only when it is needed."""

from validator.extraction import Extractor, ExtractorOutput, build_extraction
from validator.ingest import Document
from validator.models import FIELD_NAMES, Extraction

# The fields the brief lists. The others are optional: many invoices legitimately lack them, and a
# missing one must not trigger an LLM call on every such invoice.
BRIEF_FIELDS = (
    "supplier_name",
    "invoice_number",
    "invoice_date",
    "total_amount",
    "currency",
    "tax_id",
)


def needs_llm(extraction: Extraction) -> bool:
    """A found field is uncertain, or a field the brief requires is missing."""
    for name in FIELD_NAMES:
        confidence = extraction.field(name).confidence
        if 0.0 < confidence < 1.0 or (confidence == 0.0 and name in BRIEF_FIELDS):
            return True
    return False


class HybridExtractor:
    def __init__(self, heuristic: Extractor, llm: Extractor) -> None:
        self._heuristic = heuristic
        self._llm = llm

    def extract(self, document: Document) -> ExtractorOutput:
        first = self._heuristic.extract(document)
        first_scored = build_extraction(first.candidates, document)
        if not needs_llm(first_scored):
            return ExtractorOutput(candidates=first.candidates, used="hybrid:heuristic_only")
        second = self._llm.extract(document)
        second_scored = build_extraction(second.candidates, document)
        merged = {
            name: second.candidates[name]
            if second_scored.field(name).confidence >= first_scored.field(name).confidence
            else first.candidates[name]
            for name in FIELD_NAMES
        }
        return ExtractorOutput(candidates=merged, used="hybrid:llm_called", llm=second.llm)
