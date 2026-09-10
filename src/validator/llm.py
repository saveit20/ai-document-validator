"""Typed layer over the transport: builds the request and validates the model's JSON."""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from validator.extraction import Candidate, ExtractorOutput
from validator.ingest import Document
from validator.models import FIELD_NAMES, LLMCallInfo
from validator.pricing import estimate_cost_usd
from validator.prompts import DEFAULT_PROMPT, PromptSpec, build_user_prompt
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


LLMInput = Literal["text", "pdf"]


class LLMExtractor:
    """`input_mode='pdf'` also sends the original PDF, so the model sees the page layout; the
    evidence is still checked against the extracted text."""

    def __init__(
        self,
        transport: LLMTransport,
        model: str,
        input_mode: LLMInput = "text",
        prompt: PromptSpec = DEFAULT_PROMPT,
    ) -> None:
        self._transport = transport
        self._model = model
        self._input_mode = input_mode
        self._prompt = prompt

    def extract(self, document: Document) -> ExtractorOutput:
        pdf = document.data if self._input_mode == "pdf" else None
        request = LLMRequest(
            model=self._model,
            system=self._prompt.system,
            user=build_user_prompt(document.text, with_pdf=pdf is not None),
            schema=self._prompt.schema,
            prompt_version=self._prompt.version,
            pdf=pdf,
        )
        response = self._transport.complete(request)
        try:
            payload = json.loads(response.text)
            if isinstance(payload, dict):
                for name in self._prompt.preamble:
                    payload.pop(name, None)
            parsed = _InvoiceOut.model_validate(payload)
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
                self._model,
                response.input_tokens,
                response.output_tokens,
                cache_read_tokens=response.cache_read_tokens,
                cache_write_tokens=response.cache_write_tokens,
            ),
            recorded=response.recorded,
            prompt_version=self._prompt.version,
        )
        return ExtractorOutput(candidates=candidates, used="llm", llm=info)
