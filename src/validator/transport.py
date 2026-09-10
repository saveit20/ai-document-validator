"""LLM transport boundary: moves text to and from the model; never parses or validates it."""

import base64
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

import anthropic


class LLMError(Exception):
    """Base class for LLM failures that the pipeline recovers from."""


class LLMUnavailable(LLMError):
    """The call did not complete: timeout, network, rate limit, 5xx, auth, or no recording."""


class LLMInvalidOutput(LLMError):
    """The model answered, but not with usable content."""


@dataclass(frozen=True)
class LLMRequest:
    model: str
    system: str
    user: str
    schema: dict[str, Any]
    prompt_version: str
    max_tokens: int = 4096
    pdf: bytes | None = field(default=None, repr=False)
    """The original PDF, sent to the model alongside the text when the input mode is 'pdf'."""

    def cache_key(self) -> str:
        """Stable key over everything that shapes the answer; changes when the prompt changes."""
        parts: list[Any] = [self.model, self.prompt_version, self.system, self.user, self.schema]
        if self.pdf is not None:
            parts.append(hashlib.sha256(self.pdf).hexdigest())
        payload = json.dumps(parts, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    recorded: bool = False


class LLMTransport(Protocol):
    def complete(self, request: LLMRequest) -> LLMResponse: ...


_EFFORT_MODELS = ("claude-opus-5", "claude-sonnet-5")


def _user_content(request: LLMRequest) -> str | list[dict[str, Any]]:
    """The user turn: the text alone, or the PDF first (the API renders each page as an image and
    extracts its text) followed by the text."""
    if request.pdf is None:
        return request.user
    pdf = {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.b64encode(request.pdf).decode("ascii"),
        },
    }
    return [pdf, {"type": "text", "text": request.user}]


class AnthropicTransport:
    """Anthropic Messages API with JSON-schema output. The SDK retries 408/409/429/5xx itself."""

    def __init__(
        self, api_key: str, timeout_s: float = 30.0, max_retries: int = 2, client: Any = None
    ) -> None:
        self._client = client or anthropic.Anthropic(
            api_key=api_key, timeout=timeout_s, max_retries=max_retries
        )

    def complete(self, request: LLMRequest) -> LLMResponse:
        output_config: dict[str, Any] = {
            "format": {"type": "json_schema", "schema": request.schema}
        }
        if request.model.startswith(_EFFORT_MODELS):
            # Field extraction is shallow work; low effort cuts thinking tokens. Haiku 4.5 rejects it.
            output_config["effort"] = "low"
        started = time.perf_counter()
        try:
            message = self._client.messages.create(
                model=request.model,
                max_tokens=request.max_tokens,
                # The instructions are identical on every call, so they are a cacheable prefix. The
                # API ignores the marker when the prefix is below the model's minimum (4096 tokens
                # on Haiku 4.5, 1024 on Sonnet 5, 512 on Opus 5).
                system=[
                    {
                        "type": "text",
                        "text": request.system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": _user_content(request)}],
                output_config=output_config,
            )
        except anthropic.APIError as exc:
            raise LLMUnavailable(f"{type(exc).__name__}: {exc}") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)
        if message.stop_reason in ("refusal", "max_tokens"):
            raise LLMInvalidOutput(f"model stopped with stop_reason={message.stop_reason}")
        text = next((block.text for block in message.content if block.type == "text"), None)
        if text is None:
            raise LLMInvalidOutput("model returned no text block")
        return LLMResponse(
            text=text,
            model=message.model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            latency_ms=latency_ms,
            cache_read_tokens=getattr(message.usage, "cache_read_input_tokens", None) or 0,
            cache_write_tokens=getattr(message.usage, "cache_creation_input_tokens", None) or 0,
        )


class RecordedTransport:
    """Replays responses stored per model and request key. With `live`, records the misses."""

    def __init__(self, directory: Path, live: LLMTransport | None = None) -> None:
        self._directory = Path(directory)
        self._live = live

    def _path(self, request: LLMRequest) -> Path:
        return self._directory / request.model / f"{request.cache_key()}.json"

    def complete(self, request: LLMRequest) -> LLMResponse:
        path = self._path(request)
        if path.exists():
            stored = json.loads(path.read_text(encoding="utf-8"))
            return LLMResponse(**{**stored, "recorded": True})
        if self._live is None:
            raise LLMUnavailable(
                f"no recording for model={request.model} key={request.cache_key()}; "
                "record it with `python -m evals.run --record`"
            )
        response = self._live.complete(request)
        path.parent.mkdir(parents=True, exist_ok=True)
        stored = {key: value for key, value in asdict(response).items() if key != "recorded"}
        path.write_text(json.dumps(stored, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return response
