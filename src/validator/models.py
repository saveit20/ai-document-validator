"""Public data contracts: extraction results, rule configuration and API payloads."""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator, model_validator

from validator.normalize import normalize_tax_id

FieldName = Literal[
    "supplier_name",
    "invoice_number",
    "invoice_date",
    "total_amount",
    "currency",
    "tax_id",
    "subtotal_amount",
    "tax_amount",
    "customer_name",
    "customer_tax_id",
]
FIELD_NAMES: tuple[FieldName, ...] = (
    "supplier_name",
    "invoice_number",
    "invoice_date",
    "total_amount",
    "currency",
    "tax_id",
    "subtotal_amount",
    "tax_amount",
    "customer_name",
    "customer_tax_id",
)

Amount = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class Status(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    REVIEW = "REVIEW"


class FieldValue[T](BaseModel):
    """One extracted field: normalised value, confidence in [0, 1] and the text supporting it."""

    value: T | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: str | None = None
    page: int | None = None


class Extraction(BaseModel):
    supplier_name: FieldValue[str]
    invoice_number: FieldValue[str]
    invoice_date: FieldValue[date]
    total_amount: FieldValue[Amount]
    currency: FieldValue[str]
    tax_id: FieldValue[str]
    subtotal_amount: FieldValue[Amount]
    tax_amount: FieldValue[Amount]
    customer_name: FieldValue[str]
    customer_tax_id: FieldValue[str]

    def field(self, name: FieldName) -> FieldValue:
        return getattr(self, name)


class RuleConfig(BaseModel):
    """Business-rule configuration sent with every validation request."""

    model_config = ConfigDict(extra="forbid")

    document_type: Literal["SUPPLIER_INVOICE"]
    max_age_days: int = Field(gt=0)
    allowed_currencies: list[str] | None = None
    required_fields: list[FieldName] | None = None
    expected_customer_tax_id: str | None = None

    @field_validator("allowed_currencies")
    @classmethod
    def _iso_codes(cls, codes: list[str] | None) -> list[str] | None:
        if codes is None:
            return None
        normalised = [code.strip().upper() for code in codes]
        invalid = [code for code in normalised if len(code) != 3 or not code.isalpha()]
        if invalid:
            raise ValueError(f"not ISO 4217 codes: {invalid}")
        return normalised

    @field_validator("expected_customer_tax_id")
    @classmethod
    def _tax_id(cls, raw: str | None) -> str | None:
        if raw is None:
            return None
        tax_id = normalize_tax_id(raw)
        if tax_id is None:
            raise ValueError(f"not a recognised tax id: {raw!r}")
        return tax_id


class RuleResult(BaseModel):
    id: str
    passed: bool
    status: Status
    message: str


class LLMCallInfo(BaseModel):
    provider: str = "anthropic"
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None
    recorded: bool = False


class ExtractionResponse(BaseModel):
    request_id: str
    document_type: Literal["SUPPLIER_INVOICE"] = "SUPPLIER_INVOICE"
    extractor_used: str
    extraction: Extraction
    llm: LLMCallInfo | None = None
    warnings: list[str] = []


class ValidationResponse(ExtractionResponse):
    status: Status
    reference_date: date
    rules: list[RuleResult]


class DocumentIn(BaseModel):
    """Document inside a JSON request: plain text, or base64 bytes with a media type."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = None
    content_base64: str | None = None
    media_type: str | None = None
    filename: str | None = None

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "DocumentIn":
        if (self.text is None) == (self.content_base64 is None):
            raise ValueError("provide exactly one of 'text' or 'content_base64'")
        return self


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: DocumentIn


class ValidateRequest(ExtractRequest):
    config: RuleConfig
    reference_date: date | None = None
