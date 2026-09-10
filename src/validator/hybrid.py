"""Cascade: run the free heuristic first and call the LLM only when some field is uncertain."""

from validator.extraction import Extractor, ExtractorOutput, build_extraction
from validator.ingest import Document
from validator.models import FIELD_NAMES


class HybridExtractor:
    def __init__(self, heuristic: Extractor, llm: Extractor) -> None:
        self._heuristic = heuristic
        self._llm = llm

    def extract(self, document: Document) -> ExtractorOutput:
        first = self._heuristic.extract(document)
        first_scored = build_extraction(first.candidates, document)
        if all(first_scored.field(name).confidence == 1.0 for name in FIELD_NAMES):
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
