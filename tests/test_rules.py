from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from validator.models import Extraction, FieldValue, RuleConfig, RuleResult, Status
from validator.rules import DEFAULT_RULES, EvalContext, evaluate_rules, overall_status

REF = date(2026, 6, 30)
CONFIG = RuleConfig(
    document_type="SUPPLIER_INVOICE",
    max_age_days=90,
    allowed_currencies=["EUR", "GBP"],
    required_fields=["supplier_name", "invoice_number", "invoice_date", "total_amount"],
)


def fv(value, confidence: float = 1.0) -> FieldValue:
    return FieldValue(
        value=value, confidence=confidence, evidence=None if value is None else str(value)
    )


def make(**overrides: FieldValue) -> Extraction:
    fields = {
        "supplier_name": fv("ACME Ltd"),
        "invoice_number": fv("INV-1"),
        "invoice_date": fv(date(2026, 6, 15)),
        "total_amount": fv(Decimal("100.00")),
        "currency": fv("EUR"),
        "tax_id": fv("GB123456789"),
        "subtotal_amount": fv(Decimal("80.00")),
        "tax_amount": fv(Decimal("20.00")),
        "customer_name": fv("Northwind Construction S.L."),
        "customer_tax_id": fv("ESB12345678"),
    }
    return Extraction(**{**fields, **overrides})


def statuses(extraction: Extraction, config: RuleConfig = CONFIG) -> dict[str, Status]:
    return {r.id: r.status for r in evaluate_rules(extraction, config, EvalContext(REF))}


def test_clean_invoice_passes_every_rule() -> None:
    results = evaluate_rules(make(), CONFIG, EvalContext(REF))
    assert {r.status for r in results} == {Status.PASS}
    assert overall_status(results) is Status.PASS
    assert all(r.passed == (r.status is Status.PASS) for r in results)


@pytest.mark.parametrize(
    ("invoice_date", "expected"),
    [
        (REF - timedelta(days=90), Status.PASS),
        (REF - timedelta(days=91), Status.FAIL),
        (REF + timedelta(days=1), Status.FAIL),
    ],
)
def test_invoice_date_age_boundaries(invoice_date: date, expected: Status) -> None:
    assert statuses(make(invoice_date=fv(invoice_date)))["invoice_date_max_age"] is expected


@pytest.mark.parametrize(
    ("amount", "expected"), [("0.01", Status.PASS), ("0", Status.FAIL), ("-150.00", Status.FAIL)]
)
def test_total_amount_must_be_positive(amount: str, expected: Status) -> None:
    assert statuses(make(total_amount=fv(Decimal(amount))))["total_amount_positive"] is expected


def test_missing_supplier_fails_both_presence_rules() -> None:
    result = statuses(make(supplier_name=fv(None, 0.0)))
    assert result["supplier_name_present"] is Status.FAIL
    assert result["required_fields_present"] is Status.FAIL


def test_low_confidence_field_is_review_not_fail() -> None:
    results = evaluate_rules(make(total_amount=fv(Decimal("1500"), 0.6)), CONFIG, EvalContext(REF))
    by_id = {r.id: r.status for r in results}
    assert by_id["total_amount_positive"] is Status.REVIEW
    assert by_id["required_fields_present"] is Status.REVIEW
    assert overall_status(results) is Status.REVIEW


def test_found_but_unparseable_field_is_review() -> None:
    assert statuses(make(invoice_date=fv(None, 0.3)))["invoice_date_max_age"] is Status.REVIEW


def test_currency_rule_skipped_without_allowed_list() -> None:
    config = CONFIG.model_copy(update={"allowed_currencies": None})
    assert "currency_allowed" not in statuses(make(currency=fv("USD")), config)


def test_currency_outside_allowed_list_fails() -> None:
    assert statuses(make(currency=fv("USD")))["currency_allowed"] is Status.FAIL


def test_missing_currency_with_allowed_list_is_review() -> None:
    assert statuses(make(currency=fv(None, 0.0)))["currency_allowed"] is Status.REVIEW


def test_fail_takes_precedence_over_review() -> None:
    extraction = make(invoice_date=fv(date(2025, 1, 1)), total_amount=fv(Decimal("10"), 0.6))
    assert overall_status(evaluate_rules(extraction, CONFIG, EvalContext(REF))) is Status.FAIL


def test_new_rule_is_added_without_touching_existing_ones() -> None:
    class TaxIdPresent:
        id = "tax_id_present"

        def evaluate(self, extraction, config, ctx):
            present = extraction.tax_id.value is not None
            status = Status.PASS if present else Status.FAIL
            return RuleResult(id=self.id, passed=present, status=status, message="tax id check")

    results = evaluate_rules(
        make(tax_id=fv(None, 0.0)), CONFIG, EvalContext(REF), rules=(*DEFAULT_RULES, TaxIdPresent())
    )
    assert results[-1].id == "tax_id_present"
    assert results[-1].status is Status.FAIL


def test_amounts_that_do_not_add_up_are_review() -> None:
    assert statuses(make(tax_amount=fv(Decimal("30.00"))))["amounts_consistent"] is Status.REVIEW


def test_amounts_rule_skipped_without_subtotal() -> None:
    assert "amounts_consistent" not in statuses(make(subtotal_amount=fv(None, 0.0)))


@pytest.mark.parametrize(
    ("customer", "expected"),
    [("B12345678", Status.PASS), ("ESB12345678", Status.PASS), ("A46987654", Status.FAIL)],
)
def test_customer_must_match_expected_tax_id(customer: str, expected: Status) -> None:
    config = CONFIG.model_copy(update={"expected_customer_tax_id": "ESB12345678"})
    assert statuses(make(customer_tax_id=fv(customer)), config)["customer_matches"] is expected


def test_missing_customer_tax_id_is_review_when_a_customer_is_expected() -> None:
    config = CONFIG.model_copy(update={"expected_customer_tax_id": "ESB12345678"})
    assert (
        statuses(make(customer_tax_id=fv(None, 0.0)), config)["customer_matches"] is Status.REVIEW
    )


def test_customer_rule_skipped_without_expected_customer() -> None:
    assert "customer_matches" not in statuses(make())


@pytest.mark.parametrize(
    "overrides",
    [
        {"allowed_currencies": ["EURO"]},
        {"required_fields": ["iban"]},
        {"unknown": 1},
        {"max_age_days": 0},
        {"expected_customer_tax_id": "not-a-tax-id"},
    ],
)
def test_rule_config_rejects_invalid_values(overrides: dict) -> None:
    payload = {"document_type": "SUPPLIER_INVOICE", "max_age_days": 90, **overrides}
    with pytest.raises(ValidationError):
        RuleConfig.model_validate(payload)
