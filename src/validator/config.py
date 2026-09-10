"""Runtime settings, read from the environment and from `.env` when present."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_RECORDINGS_DIR = Path(__file__).resolve().parents[2] / "evals" / "recordings"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    extractor: str = "heuristic"
    llm_model: str = DEFAULT_MODEL
    llm_transport: str = "live"
    anthropic_api_key: str | None = None
    llm_timeout_s: float = 30.0
    recordings_dir: Path = DEFAULT_RECORDINGS_DIR
    log_level: str = "INFO"
    pdf_text: str = "plain"
    llm_input: str = "text"


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build settings and fail fast on combinations that cannot work."""
    if env is None:
        load_dotenv()
        env = os.environ
    settings = Settings(
        extractor=env.get("EXTRACTOR", "heuristic").strip().lower(),
        llm_model=env.get("LLM_MODEL", DEFAULT_MODEL).strip(),
        llm_transport=env.get("LLM_TRANSPORT", "live").strip().lower(),
        anthropic_api_key=env.get("ANTHROPIC_API_KEY") or None,
        llm_timeout_s=float(env.get("LLM_TIMEOUT_S", "30")),
        recordings_dir=Path(env.get("RECORDINGS_DIR", str(DEFAULT_RECORDINGS_DIR))),
        log_level=env.get("LOG_LEVEL", "INFO").strip().upper(),
        pdf_text=env.get("PDF_TEXT", "plain").strip().lower(),
        llm_input=env.get("LLM_INPUT", "text").strip().lower(),
    )
    if settings.pdf_text not in {"plain", "layout"}:
        raise ConfigError(f"PDF_TEXT must be plain or layout, not '{settings.pdf_text}'")
    if settings.llm_input not in {"text", "pdf"}:
        raise ConfigError(f"LLM_INPUT must be text or pdf, not '{settings.llm_input}'")
    if settings.extractor not in {"heuristic", "llm", "hybrid"}:
        raise ConfigError(f"EXTRACTOR must be heuristic, llm or hybrid, not '{settings.extractor}'")
    if settings.llm_transport not in {"live", "replay"}:
        raise ConfigError(f"LLM_TRANSPORT must be live or replay, not '{settings.llm_transport}'")
    if (
        settings.extractor != "heuristic"
        and settings.llm_transport == "live"
        and not settings.anthropic_api_key
    ):
        raise ConfigError(
            f"EXTRACTOR={settings.extractor} with LLM_TRANSPORT=live needs ANTHROPIC_API_KEY; "
            "set it, use LLM_TRANSPORT=replay, or use EXTRACTOR=heuristic"
        )
    return settings
