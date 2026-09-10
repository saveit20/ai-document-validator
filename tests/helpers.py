import json
from pathlib import Path

from validator.models import FIELD_NAMES
from validator.transport import LLMRequest, LLMResponse

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "evals" / "golden"


def golden_text(case_id: str) -> str:
    return (GOLDEN_DIR / f"{case_id}.txt").read_text(encoding="utf-8")


class FakeTransport:
    """Transport double: returns scripted text or raises a scripted error, and counts calls."""

    def __init__(
        self, text: str | None = None, error: Exception | None = None, model: str = "fake-model"
    ) -> None:
        self.text = text
        self.error = error
        self.model = model
        self.calls = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return LLMResponse(
            text=self.text or "",
            model=self.model,
            input_tokens=100,
            output_tokens=50,
            latency_ms=12,
        )


def llm_reply(**fields: tuple[str | None, str | None]) -> str:
    """A model reply in the output schema; fields not given are null."""
    return json.dumps(
        {
            name: {
                "value": fields.get(name, (None, None))[0],
                "evidence": fields.get(name, (None, None))[1],
            }
            for name in FIELD_NAMES
        }
    )
