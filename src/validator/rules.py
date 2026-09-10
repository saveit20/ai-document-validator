"""Business rules. To add one, write a class with `id` and `evaluate`, and list it in DEFAULT_RULES."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from validator.models import Extraction, FieldValue, RuleConfig, RuleResult, Status
from validator.normalize import same_tax_id


@dataclass(frozen=True)
class EvalContext:
    reference_date: date


class Rule(Protocol):
    id: str

    def evaluate(
        self, extraction: Extraction, config: RuleConfig, ctx: EvalContext
    ) -> RuleResult | None:
        """Return a result, or None when the rule does not apply to this config."""
        ...


def _result(rule_id: str, status: Status, message: str) -> RuleResult:
    return RuleResult(id=rule_id, passed=status is Status.PASS, status=status, message=message)


def _is_blank(field: FieldValue) -> bool:
    return field.value is None or (isinstance(field.value, str) and not field.value.strip())


def _presence_problem(rule_id: str, name: str, field: FieldValue) -> RuleResult | None:
    """REVIEW if the field was not extracted or is doubtful, None if it is present and reliable.

    An extractor that finds nothing has not proved the document lacks the field, so absence alone is
    never a FAIL: a person checks it. FAIL is kept for reliable values that break a rule.
    """
    if _is_blank(field):
        if field.confidence > 0.0:
            return _result(rule_id, Status.REVIEW, f"{name} found but could not be parsed reliably")
        return _result(
            rule_id, Status.REVIEW, f"{name} was not extracted from the document; check it manually"
        )
    if field.confidence < 1.0:
        return _result(
            rule_id, Status.REVIEW, f"{name} extracted with low confidence ({field.confidence})"
        )
    return None


class InvoiceDateMaxAge:
    id = "invoice_date_max_age"

    def evaluate(self, extraction: Extraction, config: RuleConfig, ctx: EvalContext) -> RuleResult:
        field = extraction.invoice_date
        if problem := _presence_problem(self.id, "invoice_date", field):
            return problem
        age = (ctx.reference_date - field.value).days
        if age < 0:
            return _result(
                self.id,
                Status.FAIL,
                f"invoice_date {field.value} is after the reference date {ctx.reference_date}",
            )
        if age > config.max_age_days:
            return _result(
                self.id,
                Status.FAIL,
                f"invoice_date {field.value} is {age} days old; maximum is {config.max_age_days}",
            )
        return _result(
            self.id, Status.PASS, f"invoice_date is {age} days old (max {config.max_age_days})"
        )


class TotalAmountPositive:
    id = "total_amount_positive"

    def evaluate(self, extraction: Extraction, config: RuleConfig, ctx: EvalContext) -> RuleResult:
        field = extraction.total_amount
        if problem := _presence_problem(self.id, "total_amount", field):
            return problem
        if field.value <= 0:
            return _result(
                self.id, Status.FAIL, f"total_amount {field.value} is not greater than 0"
            )
        return _result(self.id, Status.PASS, f"total_amount {field.value} is greater than 0")


class SupplierNamePresent:
    id = "supplier_name_present"

    def evaluate(self, extraction: Extraction, config: RuleConfig, ctx: EvalContext) -> RuleResult:
        field = extraction.supplier_name
        if problem := _presence_problem(self.id, "supplier_name", field):
            return problem
        return _result(self.id, Status.PASS, f"supplier_name is '{field.value}'")


class CurrencyAllowed:
    id = "currency_allowed"

    def evaluate(
        self, extraction: Extraction, config: RuleConfig, ctx: EvalContext
    ) -> RuleResult | None:
        if not config.allowed_currencies:
            return None
        field = extraction.currency
        if field.value is None:
            return _result(
                self.id,
                Status.REVIEW,
                "currency not stated in the document; cannot check it against allowed_currencies",
            )
        if field.confidence < 1.0:
            return _result(
                self.id,
                Status.REVIEW,
                f"currency extracted with low confidence ({field.confidence})",
            )
        if field.value not in config.allowed_currencies:
            return _result(
                self.id,
                Status.FAIL,
                f"currency {field.value} is not in allowed_currencies {config.allowed_currencies}",
            )
        return _result(self.id, Status.PASS, f"currency {field.value} is allowed")


class RequiredFieldsPresent:
    id = "required_fields_present"

    def evaluate(
        self, extraction: Extraction, config: RuleConfig, ctx: EvalContext
    ) -> RuleResult | None:
        if not config.required_fields:
            return None
        fields = {name: extraction.field(name) for name in config.required_fields}
        missing = [n for n, f in fields.items() if _is_blank(f)]
        doubtful = [n for n, f in fields.items() if n not in missing and f.confidence < 1.0]
        if missing:
            return _result(
                self.id,
                Status.REVIEW,
                f"required fields not extracted: {', '.join(missing)}; check them manually",
            )
        if doubtful:
            return _result(
                self.id,
                Status.REVIEW,
                f"required fields with low confidence: {', '.join(doubtful)}",
            )
        return _result(self.id, Status.PASS, "all required fields present")


class AmountsConsistent:
    """Subtotal plus tax should equal the total.

    A mismatch is REVIEW, not FAIL: withholdings (such as Spanish IRPF) and discounts legitimately
    break the identity, and so does an extraction error.
    """

    id = "amounts_consistent"
    tolerance = Decimal("0.01")

    def evaluate(
        self, extraction: Extraction, config: RuleConfig, ctx: EvalContext
    ) -> RuleResult | None:
        subtotal, tax, total = (
            extraction.subtotal_amount,
            extraction.tax_amount,
            extraction.total_amount,
        )
        if subtotal.value is None or tax.value is None or total.value is None:
            return None
        if min(subtotal.confidence, tax.confidence, total.confidence) < 1.0:
            return _result(
                self.id,
                Status.REVIEW,
                "cannot check subtotal + tax = total: low-confidence amounts",
            )
        expected = subtotal.value + tax.value
        if abs(expected - total.value) > self.tolerance:
            return _result(
                self.id,
                Status.REVIEW,
                f"subtotal {subtotal.value} + tax {tax.value} = {expected}, but total is {total.value}",
            )
        return _result(
            self.id,
            Status.PASS,
            f"subtotal {subtotal.value} + tax {tax.value} = total {total.value}",
        )


class CustomerMatches:
    id = "customer_matches"

    def evaluate(
        self, extraction: Extraction, config: RuleConfig, ctx: EvalContext
    ) -> RuleResult | None:
        expected = config.expected_customer_tax_id
        if not expected:
            return None
        field = extraction.customer_tax_id
        if field.value is None:
            return _result(
                self.id,
                Status.REVIEW,
                "customer tax id not found; cannot confirm who the invoice is addressed to",
            )
        if field.confidence < 1.0:
            return _result(
                self.id,
                Status.REVIEW,
                f"customer tax id extracted with low confidence ({field.confidence})",
            )
        if not same_tax_id(field.value, expected):
            return _result(
                self.id, Status.FAIL, f"invoice is addressed to {field.value}; expected {expected}"
            )
        return _result(
            self.id, Status.PASS, f"invoice is addressed to the expected customer {expected}"
        )


DEFAULT_RULES: tuple[Rule, ...] = (
    InvoiceDateMaxAge(),
    TotalAmountPositive(),
    SupplierNamePresent(),
    CurrencyAllowed(),
    RequiredFieldsPresent(),
    AmountsConsistent(),
    CustomerMatches(),
)


def evaluate_rules(
    extraction: Extraction,
    config: RuleConfig,
    ctx: EvalContext,
    rules: Sequence[Rule] = DEFAULT_RULES,
) -> list[RuleResult]:
    results = (rule.evaluate(extraction, config, ctx) for rule in rules)
    return [result for result in results if result is not None]


def overall_status(results: list[RuleResult]) -> Status:
    """FAIL beats REVIEW beats PASS."""
    statuses = {result.status for result in results}
    if Status.FAIL in statuses:
        return Status.FAIL
    if Status.REVIEW in statuses:
        return Status.REVIEW
    return Status.PASS
