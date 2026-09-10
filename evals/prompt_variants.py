"""Prompt variants compared on the dev split (docs/evaluation.md §9). The service uses DEFAULT_PROMPT."""

from validator.prompts import DEFAULT_PROMPT, PromptSpec

VARIANTS: dict[str, PromptSpec] = {"v3": DEFAULT_PROMPT}
