from evals.metrics import CaseResult, summarise, values_match

FIELDS_OK = {
    "supplier_name": "ACME Ltd",
    "invoice_number": "INV-1",
    "invoice_date": "2026-06-15",
    "total_amount": "100.00",
    "currency": "EUR",
    "tax_id": None,
    "subtotal_amount": None,
    "tax_amount": None,
    "customer_name": None,
    "customer_tax_id": None,
}


def test_values_match_normalises_strings_and_amounts() -> None:
    assert values_match("supplier_name", "Iberia Scaffolding S.A.", "iberia  scaffolding s.a")
    assert values_match("total_amount", "1200.00", "1200")
    assert values_match("tax_amount", "0.00", "0")
    assert values_match("tax_id", None, None)
    assert not values_match("tax_id", None, "GB1")
    assert not values_match("total_amount", "1200.00", "1.2")


def test_summary_counts_precision_recall_and_verdicts() -> None:
    wrong = {**FIELDS_OK, "total_amount": "10.00", "tax_id": "GB999999999"}
    results = [
        CaseResult("a", FIELDS_OK, FIELDS_OK, "PASS", "PASS", "heuristic"),
        CaseResult("b", FIELDS_OK, wrong, "PASS", "REVIEW", "llm", latency_ms=100, cost_usd=0.01),
    ]
    summary = summarise("test", results)
    amount = summary.fields["total_amount"]
    assert (amount.exact, amount.total, amount.tp, amount.predicted, amount.expected) == (
        1,
        2,
        1,
        2,
        2,
    )
    assert summary.fields["tax_id"].precision == 0.0
    assert summary.fields["tax_id"].recall is None
    assert summary.verdict_agreement == 0.5
    assert summary.confusion[("PASS", "REVIEW")] == 1
    assert summary.llm_calls == 1
    assert summary.cost_per_document_usd == 0.005
    assert any("b · total_amount" in failure for failure in summary.failures)


def test_summary_breaks_verdicts_down_by_difficulty() -> None:
    results = [
        CaseResult("a", FIELDS_OK, FIELDS_OK, "PASS", "PASS", "heuristic", tags=("multi_page",)),
        CaseResult(
            "b", FIELDS_OK, FIELDS_OK, "PASS", "FAIL", "heuristic", tags=("multi_page", "ocr_noise")
        ),
    ]
    summary = summarise("test", results)
    assert summary.tag_cases["multi_page"] == 2
    assert summary.tag_verdict_matches["multi_page"] == 1
    assert summary.tag_verdict_matches["ocr_noise"] == 0
