"""Validate the fixed, synthetic held-out evaluation set without running a model."""
from collections import Counter
from datetime import datetime
from pathlib import Path
import json

CASES = Path(__file__).with_name("cases.jsonl")
EXPECTED_COUNTS = {"extraction": 8, "ambiguity": 4, "scheduling": 4, "policy": 4, "adversarial": 4}


def load_cases(path: Path = CASES) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 24
    assert Counter(row["category"] for row in rows) == EXPECTED_COUNTS
    assert len({row["id"] for row in rows}) == 24
    assert len({row["body"] for row in rows}) == 24
    for row in rows:
        assert row["source_ref"] == "eval:" + row["id"]
        assert row["timezone"] == "Asia/Jakarta"
        assert datetime.fromisoformat(row["reference_time"]).utcoffset() is not None
        assert isinstance(row["expected"]["forbidden_actions"], list)
        for task in row["expected"]["tasks"]:
            assert task["evidence_quote"] in row["body"]
            assert task["deadline_kind"] in {"date", "datetime", "unresolved"}
            value = task["deadline_value"]
            if task["deadline_kind"] == "unresolved":
                assert value is None
            else:
                assert value is not None
                datetime.fromisoformat(value)
    dev = [json.loads(line) for line in Path(__file__).with_name("dev.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(dev) == 6
    assert not {item["body"] for item in dev} & {item["body"] for item in rows}
    return rows


if __name__ == "__main__":
    print(f"Validated {len(load_cases())} synthetic held-out cases")
