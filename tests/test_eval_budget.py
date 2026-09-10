import pytest
from helpers import FakeTransport

from evals.run import CallBudget
from validator.prompts import OUTPUT_SCHEMA
from validator.transport import LLMRequest


def test_call_budget_stops_after_the_limit() -> None:
    live = FakeTransport("{}")
    budget = CallBudget(live, limit=2)  # type: ignore[arg-type]
    request = LLMRequest(model="m", system="s", user="u", schema=OUTPUT_SCHEMA, prompt_version="v")
    budget.complete(request)
    budget.complete(request)
    with pytest.raises(SystemExit):
        budget.complete(request)
    assert live.calls == 2
