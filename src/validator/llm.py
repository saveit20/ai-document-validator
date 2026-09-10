"""Typed layer over the transport: builds the request and validates the model's JSON."""

import json

from pydantic import BaseModel, ConfigDict, ValidationError

from validator.extraction import Candidate, ExtractorOutput
from validator.ingest import Document
from validator.models import FIELD_NAMES, LLMCallInfo
from validator.pricing import estimate_cost_usd
from validator.prompts import OUTPUT_SCHEMA, PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from validator.transport import LLMInvalidOutput, LLMRequest, LLMTransport


class _FieldOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    evidence: str


class _InvoiceOut(BaseModel):
    """The model's answer: every field is present, and null when it is not in the document."""

    model_config = ConfigDict(extra="forbid")

    supplier_name: _FieldOut | None
    invoice_number: _FieldOut | None
    invoice_date: _FieldOut | None
    total_amount: _FieldOut | None
    currency: _FieldOut | None
    tax_id: _FieldOut | None
    subtotal_amount: _FieldOut | None
    tax_amount: _FieldOut | None
    customer_name: _FieldOut | None
    customer_tax_id: _FieldOut | None


def _candidate(field: _FieldOut | None) -> Candidate:
    if field is None or not field.value.strip():
        return Candidate()
    return Candidate(raw=field.value, evidence=field.evidence or None)


class LLMExtractor:
    def __init__(self, transport: LLMTransport, model: str) -> None:
        self._transport = transport
        self._model = model

    def extract(self, document: Document) -> ExtractorOutput:
        request = LLMRequest(
            model=self._model,
            system=SYSTEM_PROMPT,
            user=build_user_prompt(document.text),
            schema=OUTPUT_SCHEMA,
            prompt_version=PROMPT_VERSION,
        )
        response = self._transport.complete(request)
        try:
            parsed = _InvoiceOut.model_validate(json.loads(response.text))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LLMInvalidOutput(
                f"model output does not match the schema ({type(exc).__name__})"
            ) from exc
        candidates = {name: _candidate(getattr(parsed, name)) for name in FIELD_NAMES}
        info = LLMCallInfo(
            model=response.model,
            latency_ms=response.latency_ms,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            estimated_cost_usd=estimate_cost_usd(
                self._model, response.input_tokens, response.output_tokens
            ),
            recorded=response.recorded,
        )
        return ExtractorOutput(candidates=candidates, used="llm", llm=info)
