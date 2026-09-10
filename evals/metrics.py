"""Pure scoring for the evaluation harness."""

import math
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from statistics import mean

from validator.models import FIELD_NAMES


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    expected: dict[str, str | None]
    predicted: dict[str, str | None]
    expected_verdict: str
    predicted_verdict: str
    extractor_used: str
    latency_ms: int | None = None
    cost_usd: float | None = None
    tags: tuple[str, ...] = ()


_AMOUNT_FIELDS = frozenset({"total_amount", "subtotal_amount", "tax_amount"})


def _soft(text: str) -> str:
    return " ".join(text.casefold().split()).rstrip(".,")


def values_match(field_name: str, expected: str | None, predicted: str | None) -> bool:
    """Exact match after normalisation: amounts numerically, strings case- and space-insensitive."""
    if expected is None or predicted is None:
        return expected is None and predicted is None
    if field_name in _AMOUNT_FIELDS:
        try:
            return Decimal(expected) == Decimal(predicted)
        except InvalidOperation:
            return False
    return _soft(expected) == _soft(predicted)


@dataclass
class FieldStats:
    exact: int = 0
    total: int = 0
    tp: int = 0
    predicted: int = 0
    expected: int = 0

    @property
    def exact_rate(self) -> float:
        return self.exact / self.total if self.total else 0.0

    @property
    def precision(self) -> float | None:
        return self.tp / self.predicted if self.predicted else None

    @property
    def recall(self) -> float | None:
        return self.tp / self.expected if self.expected else None


@dataclass
class Summary:
    name: str
    cases: int
    fields: dict[str, FieldStats]
    verdict_matches: int = 0
    confusion: Counter[tuple[str, str]] = field(default_factory=Counter)
    llm_calls: int = 0
    fallbacks: int = 0
    latencies_ms: list[int] = field(default_factory=list)
    costs_usd: list[float] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    tag_cases: Counter[str] = field(default_factory=Counter)
    tag_verdict_matches: Counter[str] = field(default_factory=Counter)

    @property
    def field_exact_rate(self) -> float:
        exact = sum(stats.exact for stats in self.fields.values())
        total = sum(stats.total for stats in self.fields.values())
        return exact / total if total else 0.0

    @property
    def verdict_agreement(self) -> float:
        return self.verdict_matches / self.cases if self.cases else 0.0

    @property
    def p95_latency_ms(self) -> int | None:
        if not self.latencies_ms:
            return None
        ordered = sorted(self.latencies_ms)
        return ordered[math.ceil(0.95 * len(ordered)) - 1]

    @property
    def mean_latency_ms(self) -> float | None:
        return mean(self.latencies_ms) if self.latencies_ms else None

    @property
    def cost_per_document_usd(self) -> float:
        """Total LLM spend divided by all documents, including those that made no call."""
        return sum(self.costs_usd) / self.cases if self.cases else 0.0


def summarise(name: str, results: list[CaseResult]) -> Summary:
    summary = Summary(name=name, cases=len(results), fields={f: FieldStats() for f in FIELD_NAMES})
    for result in results:
        for field_name in FIELD_NAMES:
            stats = summary.fields[field_name]
            expected, predicted = result.expected[field_name], result.predicted[field_name]
            ok = values_match(field_name, expected, predicted)
            stats.total += 1
            stats.exact += ok
            stats.predicted += predicted is not None
            stats.expected += expected is not None
            stats.tp += ok and predicted is not None
            if not ok:
                summary.failures.append(
                    f"{result.case_id} · {field_name}: expected {expected!r}, got {predicted!r}"
                )
        agreed = result.expected_verdict == result.predicted_verdict
        summary.confusion[(result.expected_verdict, result.predicted_verdict)] += 1
        summary.verdict_matches += agreed
        if not agreed:
            summary.failures.append(
                f"{result.case_id} · verdict: expected {result.expected_verdict}, "
                f"got {result.predicted_verdict}"
            )
        for tag in result.tags:
            summary.tag_cases[tag] += 1
            summary.tag_verdict_matches[tag] += agreed
        if result.latency_ms is not None:
            summary.llm_calls += 1
            summary.latencies_ms.append(result.latency_ms)
            if result.cost_usd is not None:
                summary.costs_usd.append(result.cost_usd)
        if result.extractor_used.endswith("fallback"):
            summary.fallbacks += 1
    return summary


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def render(summary: Summary, show_failures: bool = True) -> str:
    lines = [
        f"## {summary.name}",
        "",
        "| Field | Exact match | Precision | Recall |",
        "|---|---|---|---|",
    ]
    for name, stats in summary.fields.items():
        lines.append(
            f"| {name} | {stats.exact}/{stats.total} ({_pct(stats.exact_rate)}) "
            f"| {_pct(stats.precision)} | {_pct(stats.recall)} |"
        )
    lines += [
        "",
        f"Verdict agreement: {summary.verdict_matches}/{summary.cases} "
        f"({_pct(summary.verdict_agreement)})",
        "",
        "| expected \\ predicted | PASS | FAIL | REVIEW |",
        "|---|---|---|---|",
    ]
    for expected in ("PASS", "FAIL", "REVIEW"):
        row = " | ".join(str(summary.confusion[(expected, p)]) for p in ("PASS", "FAIL", "REVIEW"))
        lines.append(f"| {expected} | {row} |")
    if summary.tag_cases:
        lines += ["", "| Difficulty | Cases | Verdict agreement |", "|---|---|---|"]
        for tag in sorted(summary.tag_cases):
            lines.append(
                f"| {tag} | {summary.tag_cases[tag]} "
                f"| {summary.tag_verdict_matches[tag]}/{summary.tag_cases[tag]} |"
            )
    lines += [
        "",
        f"LLM calls: {summary.llm_calls}/{summary.cases} · fallbacks: {summary.fallbacks}",
    ]
    if summary.latencies_ms:
        lines.append(
            f"Latency: mean {summary.mean_latency_ms:.0f} ms, p95 {summary.p95_latency_ms} ms · "
            f"cost per document: ${summary.cost_per_document_usd:.5f}"
        )
    if show_failures:
        lines += ["", "Failures:" if summary.failures else "Failures: none"]
        lines += [f"- {failure}" for failure in summary.failures]
    else:
        lines += ["", f"Failures: {len(summary.failures)} (hidden for the held-out set)"]
    return "\n".join(lines) + "\n"


def render_comparison(summaries: list[Summary]) -> str:
    lines = [
        "## Comparison",
        "",
        "| Configuration | Field exact match | Verdict agreement | LLM calls | Mean latency "
        "| p95 latency | Cost / document |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        mean_latency = "—" if s.mean_latency_ms is None else f"{s.mean_latency_ms:.0f} ms"
        p95 = "—" if s.p95_latency_ms is None else f"{s.p95_latency_ms} ms"
        lines.append(
            f"| {s.name} | {_pct(s.field_exact_rate)} | {_pct(s.verdict_agreement)} "
            f"| {s.llm_calls}/{s.cases} | {mean_latency} | {p95} | ${s.cost_per_document_usd:.5f} |"
        )
    return "\n".join(lines) + "\n"
