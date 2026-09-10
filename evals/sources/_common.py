"""Scenario policy and verdict computation shared by the source builders."""

import datetime as dt
import tempfile
from pathlib import Path

from validator.models import Extraction, FieldValue, RuleConfig
from validator.rules import EvalContext, evaluate_rules, overall_status

SEED = 20260910
BASE_CONFIG = {
    "document_type": "SUPPLIER_INVOICE",
    "max_age_days": 90,
    "required_fields": ["supplier_name", "invoice_number", "invoice_date", "total_amount"],
}


def default_out(source: str) -> Path:
    """Work directory used when --out is not given, so a rebuild never overwrites committed labels."""
    return Path(tempfile.gettempdir()) / "evals-sources" / source


def verdict(fields: dict, config: dict, reference: str) -> str:
    """Run the labelled values through the project's rule engine and return the overall status."""
    extraction = Extraction(
        **{
            k: FieldValue(value=v, confidence=1.0 if v is not None else 0.0)
            for k, v in fields.items()
        }
    )
    results = evaluate_rules(
        extraction,
        RuleConfig.model_validate(config),
        EvalContext(dt.date.fromisoformat(reference)),
    )
    return overall_status(results).value


def config_and_reference(
    index: int, invoice_date: str, currency: str | None
) -> tuple[dict, str, list[str]]:
    """Cycle four scenarios: two passes, a disallowed currency, and an invoice older than the window."""
    date = dt.date.fromisoformat(invoice_date)
    scenario = index % 4
    if scenario in (0, 1):
        return (
            {**BASE_CONFIG, "allowed_currencies": [currency]},
            (date + dt.timedelta(days=30)).isoformat(),
            [],
        )
    if scenario == 2:
        others = [c for c in ("EUR", "GBP", "USD") if c != currency][:1]
        return (
            {**BASE_CONFIG, "allowed_currencies": others},
            (date + dt.timedelta(days=30)).isoformat(),
            ["currency_not_allowed"],
        )
    return (
        {**BASE_CONFIG, "allowed_currencies": [currency]},
        (date + dt.timedelta(days=120)).isoformat(),
        ["date_out_of_window"],
    )
