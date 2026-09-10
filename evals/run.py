"""Golden-set evaluation over the dev set and the independently written held-out set.

python -m evals.run --extractor heuristic
python -m evals.run --extractor llm --model claude-sonnet-5            # replay recordings
python -m evals.run --extractor llm --model claude-sonnet-5 --record   # call the API for misses
python -m evals.run --all [--check-baseline | --update-baseline]
python -m evals.run --set holdout --show-holdout-failures              # only after development
"""

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

from evals.metrics import CaseResult, Summary, render, render_comparison, summarise
from validator.config import DEFAULT_MODEL
from validator.heuristic import HeuristicExtractor
from validator.hybrid import HybridExtractor
from validator.ingest import document_from_bytes
from validator.llm import LLMExtractor
from validator.models import FIELD_NAMES, RuleConfig
from validator.pipeline import Pipeline
from validator.transport import AnthropicTransport, RecordedTransport

EVALS_DIR = Path(__file__).resolve().parent
GOLDEN_DIR = EVALS_DIR / "golden"
HOLDOUT_DIR = EVALS_DIR / "holdout"
SETS = {"dev": GOLDEN_DIR, "holdout": HOLDOUT_DIR}
RECORDINGS_DIR = EVALS_DIR / "recordings"
RESULTS_DIR = EVALS_DIR / "results"
BASELINE_FILE = EVALS_DIR / "baseline.json"

MODELS = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001")
DEFAULT_CONFIG = {
    "document_type": "SUPPLIER_INVOICE",
    "max_age_days": 90,
    "allowed_currencies": ["EUR", "GBP"],
    "required_fields": ["supplier_name", "invoice_number", "invoice_date", "total_amount"],
}


@dataclass(frozen=True)
class Case:
    id: str
    path: Path
    media_type: str
    reference_date: date
    config: RuleConfig
    expected: dict[str, str | None]
    verdict: str
    tags: tuple[str, ...]


def load_cases(directory: Path) -> list[Case]:
    cases = []
    for spec_path in sorted(directory.glob("*.expected.json")):
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        document = directory / spec["document"]
        cases.append(
            Case(
                id=spec_path.name.removesuffix(".expected.json"),
                path=document,
                media_type="application/pdf" if document.suffix == ".pdf" else "text/plain",
                reference_date=date.fromisoformat(spec["reference_date"]),
                config=RuleConfig.model_validate(spec.get("config") or DEFAULT_CONFIG),
                expected={name: spec["expected"][name] for name in FIELD_NAMES},
                verdict=spec["expected"]["verdict"],
                tags=tuple(spec.get("difficulty", ())),
            )
        )
    return cases


def _as_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def evaluate(name: str, pipeline: Pipeline, cases: list[Case]) -> Summary:
    results = []
    for case in cases:
        document = document_from_bytes(case.path.read_bytes(), case.media_type, case.path.name)
        run = pipeline.validate(document, case.config, case.reference_date)
        results.append(
            CaseResult(
                case_id=case.id,
                expected=case.expected,
                predicted={f: _as_text(run.extraction.field(f).value) for f in FIELD_NAMES},
                expected_verdict=case.verdict,
                predicted_verdict=run.status.value,
                extractor_used=run.extractor_used,
                latency_ms=run.llm.latency_ms if run.llm else None,
                cost_usd=run.llm.estimated_cost_usd if run.llm else None,
                tags=case.tags,
            )
        )
    return summarise(name, results)


def build(extractor: str, model: str, record: bool) -> tuple[str, Pipeline]:
    heuristic = HeuristicExtractor()
    if extractor == "heuristic":
        return "heuristic", Pipeline(heuristic, heuristic)
    live = None
    if record:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise SystemExit("--record needs ANTHROPIC_API_KEY in the environment or in .env")
        live = AnthropicTransport(api_key)
    llm = LLMExtractor(RecordedTransport(RECORDINGS_DIR, live=live), model)
    if extractor == "llm":
        return f"llm:{model}", Pipeline(llm, heuristic)
    return f"hybrid:{model}", Pipeline(HybridExtractor(heuristic, llm), heuristic)


def _check_baseline(summaries: list[Summary]) -> int:
    if not BASELINE_FILE.exists():
        print("no baseline file; run with --update-baseline first")
        return 1
    baseline = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))
    problems = []
    for summary in summaries:
        if summary.fallbacks and not summary.name.startswith("heuristic@"):
            problems.append(
                f"{summary.name}: {summary.fallbacks} case(s) fell back to the heuristic; "
                "recordings are missing or stale (re-record with --record)"
            )
        reference = baseline.get(summary.name)
        if reference is None:
            problems.append(f"{summary.name}: no baseline entry")
            continue
        for metric in ("verdict_agreement", "field_exact_rate"):
            if getattr(summary, metric) < reference[metric] - 1e-9:
                problems.append(
                    f"{summary.name}: {metric} dropped to {getattr(summary, metric):.3f} "
                    f"(baseline {reference[metric]:.3f})"
                )
    for problem in problems:
        print(f"QUALITY GATE: {problem}")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    logging.basicConfig(level=logging.ERROR)
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--extractor", choices=("heuristic", "llm", "hybrid"), default="heuristic")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--set", choices=("dev", "holdout", "both"), default="both")
    parser.add_argument("--record", action="store_true", help="call the API for missing recordings")
    parser.add_argument("--all", action="store_true", help="heuristic, every model, and hybrid")
    parser.add_argument(
        "--show-holdout-failures",
        action="store_true",
        help="print per-case failures for the held-out set (only once development is frozen)",
    )
    gate = parser.add_mutually_exclusive_group()
    gate.add_argument("--check-baseline", action="store_true")
    gate.add_argument("--update-baseline", action="store_true")
    args = parser.parse_args(argv)

    if args.all:
        configs = [("heuristic", DEFAULT_MODEL)]
        configs += [("llm", model) for model in MODELS]
        configs += [("hybrid", DEFAULT_MODEL)]
    else:
        configs = [(args.extractor, args.model)]
    set_names = ["dev", "holdout"] if args.set == "both" else [args.set]
    pipelines = [build(extractor, model, args.record) for extractor, model in configs]
    summaries = [
        evaluate(f"{name}@{set_name}", pipeline, load_cases(SETS[set_name]))
        for set_name in set_names
        for name, pipeline in pipelines
    ]

    report = "\n".join(
        render(s, show_failures=args.show_holdout_failures or s.name.endswith("@dev"))
        for s in summaries
    )
    if len(summaries) > 1:
        report = render_comparison(summaries) + "\n" + report
    print(report)

    RESULTS_DIR.mkdir(exist_ok=True)
    target = "latest.md" if args.all else f"{configs[0][0]}_{args.set}.md"
    (RESULTS_DIR / target).write_text(report, encoding="utf-8")

    if args.update_baseline:
        baseline = (
            json.loads(BASELINE_FILE.read_text(encoding="utf-8")) if BASELINE_FILE.exists() else {}
        )
        baseline.update(
            {
                s.name: {
                    "verdict_agreement": s.verdict_agreement,
                    "field_exact_rate": s.field_exact_rate,
                }
                for s in summaries
            }
        )
        BASELINE_FILE.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    if args.check_baseline:
        return _check_baseline(summaries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
