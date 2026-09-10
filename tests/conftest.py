import pytest


@pytest.fixture(autouse=True)
def _no_real_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may reach the real Anthropic API."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
