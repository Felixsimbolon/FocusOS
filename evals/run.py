"""Opt-in extraction evaluation through the app's actual extraction service."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
from focusos_api.extractor import MODEL, PROMPT_VERSION, SCHEMA_VERSION, ExtractionFailure, extract_structured
from validate import load_cases

EVAL_CATEGORIES = {"extraction", "ambiguity", "adversarial"}

def observation(row: dict, live: bool) -> dict:
    item = {"case_id": row["id"], "category": row["category"], "model": MODEL,
            "prompt_version": PROMPT_VERSION, "schema_version": SCHEMA_VERSION,
            "status": "skipped", "latency_ms": None, "input_tokens": None,
            "output_tokens": None, "attempts": None, "tasks": []}
    if not live:
        return item
    try:
        result = extract_structured(row["source_ref"], row["body"],
                                    datetime.fromisoformat(row["reference_time"]), row["timezone"])
    except ExtractionFailure as exc:
        item["status"] = "failed"
        item["failure_code"] = exc.kind
        return item
    item.update(status="completed", model=result.model, latency_ms=result.latency_ms,
                input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                attempts=result.attempts)
    item["tasks"] = [
        {"title": task.title, "deadline_kind": task.deadline.kind,
         "deadline_value": task.deadline.value,
         "evidence_sha256": [hashlib.sha256(e.quote.encode("utf-8")).hexdigest() for e in task.evidence]}
        for task in result.result.tasks
    ]
    item["events_count"] = len(result.result.events)
    item["facts_count"] = len(result.result.facts)
    item["requests_count"] = len(result.result.requests)
    return item


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="validate and emit skipped records; no provider call")
    group.add_argument("--live", action="store_true", help="call the actual Gemini extraction service")
    parser.add_argument("--out", type=Path, default=ROOT / "evals" / "output" / "observations.jsonl")
    args = parser.parse_args()
    if args.live and not os.environ.get("GEMINI_API_KEY", "").strip():
        parser.error("GEMINI_API_KEY is required for --live")
    rows = [row for row in load_cases() if row["category"] in EVAL_CATEGORIES]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(observation(row, args.live), ensure_ascii=False) + "\n")
    print(f"Wrote {len(rows)} {'live' if args.live else 'skipped'} extraction observations to {args.out}")

if __name__ == "__main__":
    main()
