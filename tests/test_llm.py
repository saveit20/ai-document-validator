from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from helpers import FakeTransport, golden_text, llm_reply

from validator.extraction import build_extraction
from validator.heuristic import HeuristicExtractor
from validator.ingest import document_from_text
from validator.llm import LLMExtractor
from validator.models import FIELD_NAMES
from validator.pipeline import Pipeline
from validator.pricing import estimate_cost_usd
from validator.prompts import OUTPUT_SCHEMA, PROMPT_VERSION
from validator.transport import (
    AnthropicTransport,
    LLMInvalidOutput,
    LLMRequest,
    LLMUnavailable,
    RecordedTransport,
)

DOCUMENT = document_from_text(golden_text("inv_01_clean_en"))
GOOD = llm_reply(
    supplier_name=("ACME Industrial Supplies Ltd", "ACME Industrial Supplies Ltd"),
    invoice_number=("INV-2026-0142", "Invoice No: INV-2026-0142"),
    invoice_date=("2026-06-15", "Invoice date: 2026-06-15"),
    total_amount=("1200.00", "Total due (EUR) 1,200.00"),
    currency=("EUR", "Total due (EUR)"),
    tax_id=("GB123456789", "VAT Reg. No: GB123456789"),
    subtotal_amount=("1000.00", "Subtotal 1,000.00"),
    tax_amount=("200.00", "VAT 20% 200.00"),
    customer_name=("Northwind Construction S.L.", "Northwind Construction S.L."),
    customer_tax_id=("ESB12345678", "VAT: ESB12345678"),
)


def run_llm(reply: str):
    output = LLMExtractor(FakeTransport(reply), "claude-opus-5").extract(DOCUMENT)
    return output, build_extraction(output.candidates, DOCUMENT)


def test_valid_output_becomes_confident_fields_with_metadata() -> None:
    output, extraction = run_llm(GOOD)
    assert extraction.total_amount.value == Decimal("1200.00")
    assert all(extraction.field(name).confidence == 1.0 for name in FIELD_NAMES)
    assert output.used == "llm"
    assert output.llm.input_tokens == 100
    assert output.llm.estimated_cost_usd == pytest.approx((100 * 5 + 50 * 25) / 1_000_000)


@pytest.mark.parametrize(
    "reply",
    [
        "not json",
        "[]",
        '{"supplier_name": {"value": "x", "evidence": "x"}}',
        GOOD.replace('"1200.00"', "1200.00"),
    ],
)
def test_malformed_output_raises_invalid_output(reply: str) -> None:
    with pytest.raises(LLMInvalidOutput):
        LLMExtractor(FakeTransport(reply), "claude-opus-5").extract(DOCUMENT)


def test_hallucinated_value_with_real_evidence_is_low_confidence() -> None:
    _, extraction = run_llm(GOOD.replace('"1200.00"', '"9999.00"'))
    assert extraction.total_amount.confidence == 0.3


def test_evidence_not_in_document_is_low_confidence() -> None:
    reply = GOOD.replace(
        '"ACME Industrial Supplies Ltd", "evidence": "ACME Industrial Supplies Ltd"',
        '"Globex Corp", "evidence": "Globex Corp"',
    )
    _, extraction = run_llm(reply)
    assert extraction.supplier_name.confidence == 0.3


@pytest.mark.parametrize(
    "error",
    [
        LLMUnavailable("APITimeoutError: timed out"),
        LLMUnavailable("RateLimitError: 429"),
        LLMInvalidOutput("refusal"),
    ],
)
def test_pipeline_falls_back_to_heuristic(error: Exception) -> None:
    pipeline = Pipeline(
        LLMExtractor(FakeTransport(error=error), "claude-opus-5"), HeuristicExtractor()
    )
    run = pipeline.extract(DOCUMENT)
    assert run.extractor_used == "heuristic:fallback"
    assert run.llm is None
    assert len(run.warnings) == 1
    assert run.extraction.supplier_name.value == "ACME Industrial Supplies Ltd"


def _request(model: str = "claude-opus-5") -> LLMRequest:
    return LLMRequest(
        model=model, system="s", user="u", schema=OUTPUT_SCHEMA, prompt_version=PROMPT_VERSION
    )


class _StubMessages:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.kwargs = result, error, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.result


def _message(stop_reason: str = "end_turn", text: str = "{}"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        model="claude-opus-5",
        content=[SimpleNamespace(type="thinking"), SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


def _transport(messages: _StubMessages) -> AnthropicTransport:
    return AnthropicTransport(api_key="unused", client=SimpleNamespace(messages=messages))


def test_anthropic_transport_sends_structured_output_and_low_effort() -> None:
    messages = _StubMessages(result=_message(text="{}"))
    response = _transport(messages).complete(_request("claude-opus-5"))
    assert response.text == "{}"
    assert messages.kwargs["output_config"]["format"]["type"] == "json_schema"
    assert messages.kwargs["output_config"]["effort"] == "low"
    assert "temperature" not in messages.kwargs


def test_anthropic_transport_marks_the_static_system_prompt_for_caching() -> None:
    messages = _StubMessages(result=_message())
    _transport(messages).complete(_request())
    [block] = messages.kwargs["system"]
    assert block == {"type": "text", "text": "s", "cache_control": {"type": "ephemeral"}}


def test_anthropic_transport_reports_cache_tokens() -> None:
    message = _message()
    message.usage = SimpleNamespace(
        input_tokens=300,
        output_tokens=5,
        cache_read_input_tokens=1700,
        cache_creation_input_tokens=0,
    )
    response = _transport(_StubMessages(result=message)).complete(_request())
    assert (response.input_tokens, response.cache_read_tokens, response.cache_write_tokens) == (
        300,
        1700,
        0,
    )


def test_cost_prices_cache_reads_and_writes() -> None:
    # Sonnet 5: $2/MTok input; reads 0.1x, writes 1.25x.
    assert estimate_cost_usd("claude-sonnet-5", 1_000_000, 0, cache_read_tokens=1_000_000) == (
        pytest.approx(2.2)
    )
    assert estimate_cost_usd("claude-sonnet-5", 0, 0, cache_write_tokens=1_000_000) == (
        pytest.approx(2.5)
    )


def test_anthropic_transport_omits_effort_for_haiku() -> None:
    messages = _StubMessages(result=_message())
    _transport(messages).complete(_request("claude-haiku-4-5-20251001"))
    assert "effort" not in messages.kwargs["output_config"]


def test_anthropic_transport_maps_sdk_errors_to_unavailable() -> None:
    error = anthropic.APITimeoutError(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )
    with pytest.raises(LLMUnavailable):
        _transport(_StubMessages(error=error)).complete(_request())


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_anthropic_transport_rejects_unusable_stops(stop_reason: str) -> None:
    with pytest.raises(LLMInvalidOutput):
        _transport(_StubMessages(result=_message(stop_reason=stop_reason))).complete(_request())


def test_recorded_transport_records_then_replays(tmp_path) -> None:
    live = FakeTransport(GOOD)
    first = RecordedTransport(tmp_path, live=live).complete(_request())
    replayed = RecordedTransport(tmp_path).complete(_request())
    assert live.calls == 1
    assert replayed.recorded is True
    assert replayed.text == first.text


def test_recorded_transport_without_recording_is_unavailable(tmp_path) -> None:
    with pytest.raises(LLMUnavailable):
        RecordedTransport(tmp_path).complete(_request())


def test_prompt_change_invalidates_recordings() -> None:
    assert _request().cache_key() != replace(_request(), prompt_version="changed").cache_key()


def _unions(node: object) -> int:
    if isinstance(node, dict):
        own = 1 if "anyOf" in node or isinstance(node.get("type"), list) else 0
        return own + sum(_unions(value) for value in node.values())
    if isinstance(node, list):
        return sum(_unions(item) for item in node)
    return 0


def test_output_schema_respects_the_provider_union_limit() -> None:
    # Anthropic's structured outputs reject schemas with more than 16 union-typed parameters.
    assert _unions(OUTPUT_SCHEMA) <= 16


def test_null_field_means_not_found() -> None:
    _, extraction = run_llm(
        llm_reply(invoice_number=("INV-2026-0142", "Invoice No: INV-2026-0142"))
    )
    assert extraction.invoice_number.confidence == 1.0
    assert extraction.supplier_name.value is None
    assert extraction.supplier_name.confidence == 0.0
