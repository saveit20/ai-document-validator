from decimal import Decimal

from helpers import FakeTransport, golden_text, llm_reply

from validator.extraction import Candidate, ExtractorOutput, build_extraction
from validator.heuristic import HeuristicExtractor
from validator.hybrid import HybridExtractor
from validator.ingest import document_from_text
from validator.llm import LLMExtractor
from validator.pipeline import Pipeline
from validator.transport import LLMUnavailable


def hybrid(transport: FakeTransport) -> HybridExtractor:
    return HybridExtractor(HeuristicExtractor(), LLMExtractor(transport, "claude-opus-5"))


def test_confident_heuristic_skips_the_llm() -> None:
    transport = FakeTransport(llm_reply())
    output = hybrid(transport).extract(document_from_text(golden_text("inv_01_clean_en")))
    assert output.used == "hybrid:heuristic_only"
    assert output.llm is None
    assert transport.calls == 0


class _WithoutCustomer:
    """The heuristic's answer on a clean invoice, minus the optional customer fields."""

    def extract(self, document):
        output = HeuristicExtractor().extract(document)
        candidates = {
            **output.candidates,
            "customer_name": Candidate(),
            "customer_tax_id": Candidate(),
        }
        return ExtractorOutput(candidates=candidates, used=output.used)


def test_missing_optional_field_does_not_call_the_llm() -> None:
    transport = FakeTransport(llm_reply())
    extractor = HybridExtractor(_WithoutCustomer(), LLMExtractor(transport, "claude-opus-5"))
    output = extractor.extract(document_from_text(golden_text("inv_01_clean_en")))
    assert output.used == "hybrid:heuristic_only"
    assert transport.calls == 0


def test_missing_brief_field_calls_the_llm() -> None:
    transport = FakeTransport(llm_reply())
    output = hybrid(transport).extract(document_from_text("Invoice No: INV-1\nTotal 10.00 EUR\n"))
    assert output.used == "hybrid:llm_called"
    assert transport.calls == 1


def test_uncertain_heuristic_calls_llm_and_keeps_best_field() -> None:
    document = document_from_text(golden_text("inv_08_ambiguous_amount"))
    reply = llm_reply(
        supplier_name=("Globex Corp", "Globex Corp"),
        total_amount=("1500.00", "Total EUR 1.500"),
        currency=("EUR", "Total EUR 1.500"),
    )
    transport = FakeTransport(reply)
    output = hybrid(transport).extract(document)
    extraction = build_extraction(output.candidates, document)
    assert output.used == "hybrid:llm_called"
    assert transport.calls == 1
    assert output.llm is not None
    assert extraction.supplier_name.value == "Nordic Timber AB"
    assert extraction.total_amount.value == Decimal("1500.00")


def test_llm_failure_inside_hybrid_falls_back() -> None:
    pipeline = Pipeline(
        hybrid(FakeTransport(error=LLMUnavailable("timeout"))), HeuristicExtractor()
    )
    run = pipeline.extract(document_from_text(golden_text("inv_08_ambiguous_amount")))
    assert run.extractor_used == "heuristic:fallback"
