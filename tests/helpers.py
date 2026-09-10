from pathlib import Path

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "evals" / "golden"


def golden_text(case_id: str) -> str:
    return (GOLDEN_DIR / f"{case_id}.txt").read_text(encoding="utf-8")
