"""Orchestration: extract (with fallback) → normalise and score → rules → verdict."""

import logging
from dataclasses import dataclass
from datetime import date

from validator.config import Settings
from validator.extraction import Extractor, build_extraction
from validator.heuristic import HeuristicExtractor
from validator.ingest import Document
from validator.models import Extraction, LLMCallInfo, RuleConfig, RuleResult, Status
from validator.rules import EvalContext, evaluate_rules, overall_status
from validator.transport import LLMError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractionRun:
    extraction: Extraction
    extractor_used: str
    llm: LLMCallInfo | None
    warnings: list[str]


@dataclass(frozen=True)
class ValidationRun(ExtractionRun):
    status: Status
    rules: list[RuleResult]
    reference_date: date


class Pipeline:
    def __init__(self, extractor: Extractor, fallback: Extractor) -> None:
        self._extractor = extractor
        self._fallback = fallback

    def extract(self, document: Document) -> ExtractionRun:
        warnings: list[str] = []
        try:
            output = self._extractor.extract(document)
            used = output.used
        except LLMError as exc:
            logger.warning(
                "llm_extraction_failed", extra={"error": type(exc).__name__, "detail": str(exc)}
            )
            warnings.append(
                f"LLM extraction failed ({type(exc).__name__}); used the heuristic extractor instead"
            )
            output = self._fallback.extract(document)
            used = "heuristic:fallback"
        extraction = build_extraction(output.candidates, document)
        return ExtractionRun(extraction, used, output.llm, warnings)

    def validate(
        self, document: Document, config: RuleConfig, reference_date: date
    ) -> ValidationRun:
        run = self.extract(document)
        results = evaluate_rules(run.extraction, config, EvalContext(reference_date))
        return ValidationRun(
            extraction=run.extraction,
            extractor_used=run.extractor_used,
            llm=run.llm,
            warnings=run.warnings,
            status=overall_status(results),
            rules=results,
            reference_date=reference_date,
        )


def build_pipeline(settings: Settings) -> Pipeline:
    heuristic = HeuristicExtractor()
    return Pipeline(heuristic, fallback=heuristic)
