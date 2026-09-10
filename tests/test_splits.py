"""The committed dev/test manifest: every case in exactly one split, every source split about 50/50."""

import json
from collections import Counter
from pathlib import Path

from evals.run import SOURCES, SPLITS_FILE


def test_every_case_is_in_exactly_one_split_and_each_source_is_halved() -> None:
    splits = json.loads(SPLITS_FILE.read_text(encoding="utf-8"))
    dev, test = set(splits["dev"]), set(splits["test"])
    assert not dev & test
    for source, directory in SOURCES.items():
        ids = {
            p.name.removesuffix(".expected.json") for p in Path(directory).glob("*.expected.json")
        }
        assert ids <= dev | test, f"{source} has cases in no split"
        counts = Counter("dev" if case in dev else "test" for case in ids)
        assert abs(counts["dev"] - counts["test"]) <= 1, f"{source} is not split in half: {counts}"
