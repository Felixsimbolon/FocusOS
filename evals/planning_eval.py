"""Synthetic planning evaluation. Neither mode reads Gmail nor writes Calendar."""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
from focusos_api.agent_planner import PROMPT_VERSION, SELECTION_SCHEMA_VERSION, PlanningModelError, select_planning_intent
from focusos_api.gemini import MODEL, api_key
from focusos_api.planning_compiler import compile_plan
from focusos_api.planning_contract import PlanningValidationError
from focusos_api.profiles import ProfileRecord, WorkingHours

REFERENCE = datetime(2026, 10, 2, 1, tzinfo=timezone.utc)
PROFILE = ProfileRecord(id=UUID(int=1), timezone="Asia/Jakarta",
    working_hours=WorkingHours(days=[1, 2, 3, 4, 5, 6, 7], start_minute=540, end_minute=1020))
TASK = {"id": str(UUID(int=2)), "title": "Prepare the FocusOS demo checklist",
        "estimate_minutes": 30, "due_kind": "none", "due_at": None, "due_date": None}


def intent(**changes):
    return {"status": "selected", "task_refs": ["task-1"], "duration_minutes": 30,
        "day": "tomorrow", "date": None, "start_time": None, "end_time": None,
        "evidence_refs": [], "questions": [], **changes}


def cases():
    command = 'Schedule the task "Prepare the FocusOS demo checklist" for 30 minutes tomorrow.'
    return [
        {"id": "tomorrow_30", "command": command, "expected": "proposed", "duration": 30, "selection": intent()},
        {"id": "tomorrow_60", "command": command.replace("30", "60"), "expected": "proposed", "duration": 60,
         "selection": intent(duration_minutes=60)},
        {"id": "indonesian", "command": 'Jadwalkan task "Prepare the FocusOS demo checklist" selama 30 menit besok.',
         "expected": "proposed", "duration": 30, "selection": intent()},
        {"id": "saved_estimate", "command": 'Schedule the task "Prepare the FocusOS demo checklist" tomorrow.',
         "expected": "proposed", "duration": 30, "selection": intent(duration_minutes=None)},
        {"id": "duration_conflict", "command": command, "override": 60, "expected": "needs_clarification",
         "code": "duration_conflict", "selection": intent()},
        {"id": "date_only", "command": command, "task": {**TASK, "due_kind": "date", "due_date": "2026-10-05"},
         "expected": "proposed", "duration": 30, "selection": intent()},
        {"id": "past_date_only", "command": command, "task": {**TASK, "due_kind": "date", "due_date": "2026-10-01"},
         "expected": "needs_clarification", "code": "deadline_passed", "selection": intent()},
        {"id": "past_deadline", "command": command,
         "task": {**TASK, "due_kind": "datetime", "due_at": "2026-10-01T17:00:00+07:00"},
         "expected": "needs_clarification", "code": "deadline_passed", "selection": intent()},
        {"id": "full_calendar", "command": command, "busy": True, "expected": "insufficient_time",
         "code": "insufficient_time", "selection": intent()},
    ]


def evaluate(live: bool) -> dict:
    observations = []
    for case in cases():
        snapshot = {"complete": True, "timezone": PROFILE.timezone, "start": REFERENCE.isoformat(),
            "end": (REFERENCE+timedelta(days=7)).isoformat(), "fetched_at": REFERENCE.isoformat(), "events": []}
        if case.get("busy"):
            snapshot["events"] = [{"id": "synthetic-busy", "title": "Busy", "start": "2026-10-03T09:00:00+07:00",
                                   "end": "2026-10-03T17:00:00+07:00"}]
        checkpoint = {"duration_minutes": case.get("override"), "allow_split": False,
            "timezone": PROFILE.timezone, "window_start": REFERENCE.isoformat(), "calendar": snapshot,
            "memory_search": {"mode": "none", "matches": []}}
        tasks = [case.get("task", TASK)]
        observation = {"id": case["id"], "expected_status": case["expected"], "passed": False}
        try:
            raw = select_planning_intent(case["command"], tasks, {}, reference_time=REFERENCE.isoformat(),
                timezone_name=PROFILE.timezone, duration_minutes=case.get("override"), allow_split=False) if live else case["selection"]
            result, free = compile_plan(raw, tasks, checkpoint, PROFILE, now=REFERENCE, command=case["command"])
            observation.update(status=result["status"], safe_code=result.get("safe_code"),
                               scheduled_minutes=result["scheduled_minutes"])
            passed = result["status"] == case["expected"]
            if "code" in case:
                passed = passed and result.get("safe_code") == case["code"]
            if result["status"] == "proposed":
                from zoneinfo import ZoneInfo
                day = datetime.fromisoformat(result["blocks"][0]["start"]).astimezone(ZoneInfo(PROFILE.timezone)).date()
                passed = passed and day.isoformat() == "2026-10-03" and result["scheduled_minutes"] == case["duration"]
                passed = passed and free.allocated_minutes == result["scheduled_minutes"]
                if tasks[0].get("due_kind") == "date":
                    deadline_day = datetime.fromisoformat(tasks[0]["due_date"]).date()
                    passed = passed and all(datetime.fromisoformat(block["end"]).astimezone(ZoneInfo(PROFILE.timezone)).date() <= deadline_day for block in result["blocks"])
            else:
                passed = passed and not result["blocks"] and not free.slots
            observation["passed"] = passed
        except (PlanningModelError, PlanningValidationError) as exc:
            observation.update(status="failed", safe_code=exc.code)
        observations.append(observation)
    return {"mode": "live_model_synthetic_calendar" if live else "mock_selection_backend_regression",
        "provider_called": live, "calendar_written": False, "model": MODEL if live else None,
        "prompt_version": PROMPT_VERSION, "selection_schema_version": SELECTION_SCHEMA_VERSION,
        "reference_time": REFERENCE.isoformat(), "total": len(observations),
        "passed": sum(row["passed"] for row in observations), "observations": observations}


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--mock", action="store_true", help="use fixture selections; does not measure Gemini quality")
    mode.add_argument("--live", action="store_true", help="call Gemini only, with synthetic tasks and Calendar")
    parser.add_argument("--out", type=Path, default=ROOT / "evals/output/planning.json")
    args = parser.parse_args()
    if args.live and not api_key():
        parser.error("GEMINI_API_KEY is required for live model evaluation")
    report = evaluate(args.live)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(f"{report['mode']}: {report['passed']}/{report['total']} passed; Calendar writes: 0")
    for row in report["observations"]:
        if not row["passed"]:
            print(f"FAILED {row['id']}: {row.get('safe_code') or row.get('status')}")
    if report["passed"] != report["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
