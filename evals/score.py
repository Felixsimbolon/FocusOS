"""One-to-one extraction scoring with explicit human title adjudication."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from validate import load_cases

ROOT = Path(__file__).resolve().parents[1]


def norm(value: str) -> str:
    return " ".join(value.casefold().split())


def score_case(case: dict, record: dict, judgments: dict[tuple[str, str, str], bool]) -> dict:
    expected = case["expected"]["tasks"]
    predicted = record.get("tasks", []) if record.get("status") == "completed" else []
    available = set(range(len(predicted)))
    matches = []
    needs_review = []
    for label in expected:
        exact = [i for i in available if norm(predicted[i]["title"]) == norm(label["title"])]
        manual = [i for i in available if judgments.get((case["id"], predicted[i]["title"], label["title"])) is True]
        chosen = min(exact) if exact else min(manual) if manual else None
        if chosen is None:
            for i in available:
                if (case["id"], predicted[i]["title"], label["title"]) not in judgments:
                    needs_review.append({"observed_title": predicted[i]["title"], "expected_title": label["title"]})
            continue
        available.remove(chosen)
        actual = predicted[chosen]
        expected_hash = hashlib.sha256(label["evidence_quote"].encode("utf-8")).hexdigest()
        matches.append({"deadline_correct": actual.get("deadline_kind") == label["deadline_kind"]
                        and actual.get("deadline_value") == label["deadline_value"],
                        "evidence_correct": expected_hash in actual.get("evidence_sha256", [])})
    return {"case_id": case["id"], "status": record["status"], "expected": len(expected),
            "predicted": len(predicted), "matched": len(matches), "false_positive": len(available),
            "missed": len(expected) - len(matches),
            "deadline_correct": sum(item["deadline_correct"] for item in matches),
            "evidence_correct": sum(item["evidence_correct"] for item in matches),
            "needs_review": needs_review}


def make_report(cases: list[dict], observations: list[dict], judgments: dict) -> str:
    relevant = [row for row in cases if row["category"] in {"extraction", "ambiguity", "adversarial"}]
    by_id = {row["case_id"]: row for row in observations}
    if len(by_id) != len(observations) or set(by_id) != {row["id"] for row in relevant}:
        raise ValueError("Observations must cover each extraction case exactly once")
    states = Counter(row["status"] for row in observations)
    if set(states) - {"completed", "failed", "skipped"}:
        raise ValueError("Unknown observation status")
    measured = [row for row in relevant if by_id[row["id"]]["status"] != "skipped"]
    scores = [score_case(row, by_id[row["id"]], judgments) for row in measured]
    total = lambda key: sum(item[key] for item in scores)
    versions = sorted({(str(row.get("model")), str(row.get("prompt_version")), str(row.get("schema_version"))) for row in observations})
    lines = ["# FocusOS extraction evaluation", "", f"Cases: {len(relevant)} extraction/ambiguity/adversarial; 8 scheduling/policy safety cases excluded.",
             f"Completed: {states['completed']}/{len(relevant)}; failed: {states['failed']}/{len(relevant)}; skipped: {states['skipped']}/{len(relevant)}.",
             f"Model/prompt/schema versions: {', '.join('/'.join(v) for v in versions)}.", ""]
    if not measured:
        lines += ["No live model result is available. Accuracy is **not measured**; dry-run records are not scored.", ""]
    else:
        expected = total("expected"); predicted = total("predicted"); matched = total("matched")
        lines += [f"One-to-one task match: {matched}/{expected} expected; precision {matched}/{predicted} predicted (N/A when denominator is zero).",
                  f"Exact deadline kind/value: {total('deadline_correct')}/{expected} expected tasks.",
                  f"Expected evidence quote SHA-256 present: {total('evidence_correct')}/{expected} expected tasks.",
                  f"Unmatched expected tasks: {total('missed')}; extra tasks: {total('false_positive')}.",
                  "Failed calls count as missing expected tasks. Semantic title variants require recorded human judgments; unmatched pairs are not silently treated as correct.", "",
                  "| Case | Status | Matched/expected | Deadline | Evidence | Extra | Needs title review |",
                  "| --- | --- | ---: | ---: | ---: | ---: | ---: |"]
        for item in scores:
            lines.append(f"| {item['case_id']} | {item['status']} | {item['matched']}/{item['expected']} | {item['deadline_correct']} | {item['evidence_correct']} | {item['false_positive']} | {len(item['needs_review'])} |")
        lines.append("")
    lines += ["Limitations: synthetic held-out source text; task matching first uses normalized exact titles, then explicit reviewer judgments. No live Gmail, Calendar write, or scheduling score is implied.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", type=Path, default=ROOT / "evals/output/observations.jsonl")
    parser.add_argument("--judgments", type=Path, default=ROOT / "evals/output/judgments.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "evals/output/report.md")
    args = parser.parse_args()
    observations = [json.loads(line) for line in args.observations.read_text(encoding="utf-8").splitlines() if line.strip()]
    judgments = {}
    if args.judgments.exists():
        for line in args.judgments.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            key = (row["case_id"], row["observed_title"], row["expected_title"])
            if key in judgments or not isinstance(row["equivalent"], bool):
                raise ValueError("Duplicate or invalid reviewer judgment")
            judgments[key] = row["equivalent"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(make_report(load_cases(), observations, judgments), encoding="utf-8")
    print(args.out)

if __name__ == "__main__":
    main()
