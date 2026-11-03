"""Deadline forecast: how likely each open task is to be finished by its deadline, and what would save the ones at risk.

A Monte Carlo simulation over what is actually uncertain, using only the user's own data and no model call:
- how long the work takes: the saved estimate, minus work already checked in, times a duration factor sampled around
  the user's learned factor (estimates.py: log-normal, its spread from the same check-ins);
- whether a booked FocusOS block happens: kept at the user's show-up rate from check-ins (done or partial vs skipped);
- how much unbooked free time goes to planned work: a share of the working-hours time Calendar shows free, sampled per
  day around one half, since meetings, rest and errands take the rest.

Each run spends time earliest-deadline-first, the order that meets the most deadlines on one person's time: a booked
block goes to its own task, and free time to the open task with the nearest deadline. So a task only competes with
tasks due before it, and a what-if that defers one of those shows exactly what it frees. Runs are seeded per user and
day, so the forecast is stable across refreshes and changes only when the data does. Nothing is written.
"""
import math
import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from focusos_api import estimates
from focusos_api.calendar_domain import CalendarEventError
from focusos_api.calendar_fetch import CalendarFetchError, fetch_calendar_window
from focusos_api.calendar_free_time import CalendarPlanningError, _merge, _subtract, _work_intervals
from focusos_api.calendar_normalize import normalize_window, occurrence_interval
from focusos_api.database import scoped_client
from focusos_api.google_calendar import CalendarReconnectRequired
from focusos_api.profiles import read_profile
from focusos_api.tasks import list_tasks

HORIZON_DAYS = 14             # the longest Calendar window FocusOS reads
RUNS = 400
WHAT_IF_RUNS = 200
MAX_TASKS = 30                # the nearest deadlines; later ones cannot affect these (earliest deadline first)
UNESTIMATED_MINUTES = 60      # a task without an estimate is forecast as one hour, and flagged
FREE_TIME_USE = (4.0, 4.0)    # Beta: about half of free working time goes to planned work, varying day to day
SHOW_UP_PRIOR = (4.0, 1.0)    # Beta: about 80% of booked blocks happen, until check-ins say otherwise
SAFE, TIGHT = 0.8, 0.5        # on-time probability bands
WHAT_IF_GAIN = 0.15           # a deferral is suggested only when it raises the chance this much
WHAT_IF_TASKS, WHAT_IF_COMPETITORS = 3, 3
SESSION_MINUTES = 90
PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}


class ForecastUnavailable(Exception):
    """The forecast needs the user's timezone and working hours first."""


@dataclass(frozen=True)
class Work:
    id: str
    title: str
    priority: str
    project_id: str | None
    deadline: datetime
    remaining: float          # estimate minutes not yet covered by checked-in work
    estimated: bool
    factor: estimates.Estimate


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime
    day: int                  # local days from today, for the per-day share of free time
    task: str | None = None   # a booked block's task; None for free time

    @property
    def minutes(self) -> float:
        return (self.end - self.start).total_seconds() / 60


def deadline_of(task, zone: ZoneInfo) -> datetime | None:
    """A date deadline means by the end of that local day."""
    if task.due_kind == "datetime" and task.due_at is not None:
        return task.due_at.astimezone(timezone.utc)
    if task.due_kind == "date" and task.due_date is not None:
        return datetime.combine(task.due_date + timedelta(days=1), time.min, tzinfo=zone).astimezone(timezone.utc)
    return None


def covered_minutes(sessions: list[dict]) -> dict[str, float]:
    """Estimate minutes each task's checked-in blocks covered. A finished block covered what it was planned for; a
    partial one the share it got through (planned / what the chunk really needed)."""
    covered: dict[str, float] = {}
    for row in sessions:
        task, planned, actual, outcome = row.get("task_id"), row.get("planned_minutes"), row.get("actual_minutes"), row.get("outcome")
        if not task or not isinstance(planned, int) or planned <= 0 or outcome not in ("done", "partial"):
            continue
        share = 1.0 if outcome == "done" or not isinstance(actual, int) or actual <= 0 else min(1.0, planned / actual)
        covered[str(task)] = covered.get(str(task), 0.0) + planned * share
    return covered


def show_up(sessions: list[dict]) -> tuple[float, float]:
    kept = sum(1 for row in sessions if row.get("outcome") in ("done", "partial"))
    skipped = sum(1 for row in sessions if row.get("outcome") == "skipped")
    return SHOW_UP_PRIOR[0] + kept, SHOW_UP_PRIOR[1] + skipped


def _duration_factor(rng: random.Random, estimate: estimates.Estimate) -> float:
    sigma = max(0.0, (math.log(estimate.high) - math.log(estimate.low)) / 2)
    low, high = estimates.FACTOR_RANGE
    return min(high, max(low, math.exp(rng.normalvariate(math.log(estimate.factor), sigma))))


def simulate(works: list[Work], slots: list[Slot], keep: tuple[float, float], now: datetime, *, runs: int, seed: str,
             days: int = HORIZON_DAYS + 1) -> tuple[dict[str, list[datetime | None]], dict[str, list[float]]]:
    """Finish times (None: not finished inside the horizon) and sampled minutes of work, per task and run."""
    rng = random.Random(seed)
    order = [work.id for work in sorted(works, key=lambda work: (work.deadline, PRIORITY_RANK.get(work.priority, 1), work.title, work.id))]
    finishes: dict[str, list[datetime | None]] = {work.id: [] for work in works}
    needs: dict[str, list[float]] = {work.id: [] for work in works}
    for _ in range(runs):
        need = {work.id: work.remaining * _duration_factor(rng, work.factor) for work in works}
        for work in works: needs[work.id].append(need[work.id])
        kept = rng.betavariate(*keep)
        share = [rng.betavariate(*FREE_TIME_USE) for _ in range(days)]
        finish = {task: now for task, minutes in need.items() if minutes <= 0}
        cursor = 0
        for slot in slots:
            if slot.task is not None and (slot.task not in need or rng.random() >= kept):
                continue
            rate = 1.0 if slot.task is not None else share[min(slot.day, days - 1)]
            capacity, used = slot.minutes * rate, 0.0
            # A booked block works on its own task first; whatever is left goes earliest-deadline-first.
            own = [slot.task] if slot.task is not None and slot.task not in finish else []
            while capacity - used > 1e-9:
                if own:
                    task = own.pop()
                else:
                    while cursor < len(order) and order[cursor] in finish: cursor += 1
                    if cursor >= len(order): break
                    task = order[cursor]
                take = min(need[task], capacity - used)
                need[task] -= take
                used += take
                if need[task] <= 1e-9:
                    finish[task] = slot.start + timedelta(minutes=used / rate)
            if cursor >= len(order) and len(finish) == len(need): break
        for work in works: finishes[work.id].append(finish.get(work.id))
    return finishes, needs


def _quantile(values: list, q: float):
    """A quantile where None (not finished in the horizon) sorts last."""
    ranked = sorted(values, key=lambda value: (value is None, value or 0))
    return ranked[min(len(ranked) - 1, int(q * len(ranked)))] if ranked else None


def _probability(finishes: list[datetime | None], deadline: datetime) -> float:
    return sum(1 for value in finishes if value is not None and value <= deadline) / len(finishes) if finishes else 0.0


def band(probability: float) -> str:
    return "safe" if probability >= SAFE else "tight" if probability >= TIGHT else "at_risk"


def _round5(minutes: float) -> int:
    return int(5 * math.ceil(minutes / 5))


def _local(value: datetime, zone: ZoneInfo) -> str:
    return value.astimezone(zone).strftime("%a %d %b %H:%M")


def booking_request(title: str, minutes: int, deadline: datetime, zone: ZoneInfo) -> str:
    """A request the composer can send as is: the existing pipeline books it, with the usual approval."""
    sessions = max(1, math.ceil(minutes / SESSION_MINUTES))
    each = max(15, _round5(minutes / sessions))
    local = (deadline - timedelta(minutes=1)).astimezone(zone)
    plan = f"{sessions} sessions of {each} minutes" if sessions > 1 else f"{each} minutes"
    return f'Book {plan} for "{title}" before {local:%A %d %B} {local:%H:%M}'


def suggestions(work: Work, probability: float, need_p80: float, booked: float, free: float, keep_rate: float,
                zone: ZoneInfo) -> list[dict]:
    found = []
    if not work.estimated:
        found.append({"kind": "estimate", "text": f"No estimate saved, so this assumes {UNESTIMATED_MINUTES} minutes. Add one for a real forecast."})
    if probability >= SAFE:
        return found
    gap = need_p80 - booked * keep_rate
    if gap > 0 and free >= gap:
        minutes = _round5(gap)
        found.append({"kind": "book", "minutes": minutes, "request": booking_request(work.title, minutes, work.deadline, zone),
                      "text": f"Book about {minutes} more minutes before the deadline; free time alone is not reliably enough."})
    elif gap > 0:
        short = _round5(gap - free)
        found.append({"kind": "renegotiate", "minutes": short,
                      "text": f"Even every free minute before the deadline leaves about {short} minutes short. Ask for more time or cut scope."})
    return found


def what_ifs(work: Work, works: list[Work], slots: list[Slot], keep: tuple[float, float], now: datetime, seed: str,
             probability: float) -> list[dict]:
    """Defer a task due no later than this one, of equal or lower priority: how much would this task gain?"""
    rank = PRIORITY_RANK.get(work.priority, 1)
    competitors = sorted((other for other in works if other.id != work.id and other.deadline <= work.deadline
                          and PRIORITY_RANK.get(other.priority, 1) >= rank and other.remaining > 0),
                         key=lambda other: (-PRIORITY_RANK.get(other.priority, 1), -other.remaining))[:WHAT_IF_COMPETITORS]
    found = []
    for other in competitors:
        rest = [item for item in works if item.id != other.id]
        finishes, _ = simulate(rest, slots, keep, now, runs=WHAT_IF_RUNS, seed=seed)
        chance = _probability(finishes[work.id], work.deadline)
        if chance - probability >= WHAT_IF_GAIN:
            found.append({"kind": "defer", "task_id": other.id, "title": other.title, "probability": round(chance, 2),
                          "text": f'Moving "{other.title}" after this deadline raises the chance to {round(chance * 100)}%.'})
    return sorted(found, key=lambda item: -item["probability"])[:2]


def _payload_interval(row: dict) -> tuple[datetime, datetime] | None:
    payload = row.get("payload")
    if not isinstance(payload, dict) or row.get("cancellation_status") == "cancelled":
        return None
    try:
        start, end = datetime.fromisoformat(payload["start"]), datetime.fromisoformat(payload["end"])
    except (KeyError, TypeError, ValueError):
        return None
    if start.tzinfo is None or end <= start:
        return None
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def build_slots(now: datetime, end: datetime, zone: ZoneInfo, hours, busy: list[tuple[datetime, datetime]],
                blocks: list[tuple[datetime, datetime, str | None]], tasks: set[str]) -> list[Slot]:
    """Free working time (Calendar busy time and every booked block removed) plus each forecast task's booked blocks."""
    today = now.astimezone(zone).date()
    day = lambda value: (value.astimezone(zone).date() - today).days  # noqa: E731
    taken = _merge([(max(a, now), min(b, end)) for a, b in busy + [(a, b) for a, b, _ in blocks] if b > now and a < end])
    slots = [Slot(a, b, day(a)) for a, b in _subtract(_work_intervals(now, end, zone, hours), taken)]
    slots += [Slot(max(a, now), min(b, end), day(max(a, now)), task) for a, b, task in blocks
              if task in tasks and b > now and a < end]
    return sorted(slots, key=lambda slot: (slot.start, slot.task is None))


def forecast(token: str, now: datetime | None = None) -> dict:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    profile = read_profile(token)
    if profile is None:
        raise ForecastUnavailable("profile_required")
    zone = ZoneInfo(profile.timezone)
    horizon = current + timedelta(days=HORIZON_DAYS)
    open_tasks = list_tasks(token, status="open", limit=200).tasks
    with scoped_client(token) as (owner, client):
        rows = (client.table("approval_requests").select("id,task_id,event_id,provider_event_id,payload,cancellation_status")
                .eq("user_id", owner).eq("status", "succeeded").order("created_at", desc=True).limit(200).execute().data)
        sessions = (client.table("work_sessions").select("approval_id,task_id,project_id,planned_minutes,actual_minutes,outcome")
                    .eq("user_id", owner).order("created_at", desc=True).limit(estimates.HISTORY).execute().data)
    rows = rows if isinstance(rows, list) else []
    sessions = sessions if isinstance(sessions, list) else []
    factors, covered, keep = estimates.estimate_factors(sessions), covered_minutes(sessions), show_up(sessions)

    dated = sorted(((deadline_of(task, zone), task) for task in open_tasks), key=lambda item: (item[0] is None, item[0] or current))
    overdue = [{"id": str(task.id), "title": task.title, "deadline": deadline.isoformat()} for deadline, task in dated
               if deadline is not None and deadline <= current]
    upcoming = [(deadline, task) for deadline, task in dated if deadline is not None and current < deadline <= horizon]
    works = [Work(str(task.id), task.title, task.priority, str(task.project_id) if task.project_id else None, deadline,
                  max(0.0, (task.estimate_minutes or UNESTIMATED_MINUTES) - covered.get(str(task.id), 0.0)),
                  task.estimate_minutes is not None, estimates.factor_for(factors, task.project_id))
             for deadline, task in upcoming[:MAX_TASKS]]
    result = {"generated_at": current.isoformat(), "timezone": profile.timezone, "horizon_end": horizon.isoformat(),
              "calendar": "not_needed", "tasks": [], "overdue": overdue, "unchecked_blocks": 0,
              "later": sum(1 for deadline, _ in dated if deadline is not None and deadline > horizon) + max(0, len(upcoming) - MAX_TASKS),
              "undated": sum(1 for deadline, _ in dated if deadline is None),
              "assumptions": {"check_ins": sum(1 for row in sessions if row.get("outcome") in ("done", "partial", "skipped")),
                              "show_up_rate": round(keep[0] / sum(keep), 2), "free_time_use": round(FREE_TIME_USE[0] / sum(FREE_TIME_USE), 2),
                              "duration_factor": factors["overall"].as_dict(), "runs": RUNS}}
    if not works:
        return result

    end = max(work.deadline for work in works)
    blocks = [(interval[0], interval[1], str(row["task_id"]) if row.get("task_id") else None)
              for row in rows if (interval := _payload_interval(row))]
    own = {str(value) for row in rows for value in (row.get("event_id"), row.get("provider_event_id")) if value}
    try:
        window = fetch_calendar_window(token, current, end)
        if not window.complete:
            raise CalendarFetchError("incomplete")
        busy = [occurrence_interval(item) for item in normalize_window(window) if item.provider_id not in own]
        result["calendar"] = "read"
    except (CalendarReconnectRequired, CalendarFetchError, CalendarEventError):
        # Without Calendar every working hour outside booked blocks counts as free: the forecast is optimistic, and says so.
        busy, result["calendar"] = [], "unavailable"
    try:
        slots = build_slots(current, end, zone, profile.working_hours, busy, blocks, {work.id for work in works})
    except CalendarPlanningError as exc:
        raise ForecastUnavailable("working_hours") from exc

    seed = f"{owner}:{current.astimezone(zone).date().isoformat()}"
    finishes, needs = simulate(works, slots, keep, current, runs=RUNS, seed=seed)
    keep_rate = keep[0] / sum(keep)
    # Blocks that ended without a check-in count as no progress; checking in makes the forecast less pessimistic.
    checked, forecast_ids = {str(row.get("approval_id")) for row in sessions}, {work.id for work in works}
    result["unchecked_blocks"] = sum(1 for row in rows if str(row.get("task_id")) in forecast_ids and str(row.get("id")) not in checked
                                     and (interval := _payload_interval(row)) and interval[1] <= current)
    entries = []
    for work in works:
        probability = _probability(finishes[work.id], work.deadline)
        booked = sum(slot.minutes for slot in slots if slot.task == work.id and slot.start < work.deadline)
        free = sum(slot.minutes for slot in slots if slot.task is None and slot.start < work.deadline)
        need_p50, need_p80 = _quantile(needs[work.id], 0.5), _quantile(needs[work.id], 0.8)
        p50, p80 = _quantile(finishes[work.id], 0.5), _quantile(finishes[work.id], 0.8)
        entries.append({"id": work.id, "title": work.title, "priority": work.priority, "project_id": work.project_id,
                        "deadline": work.deadline.isoformat(), "probability": round(probability, 2), "status": band(probability),
                        "estimated": work.estimated, "remaining_minutes": round(work.remaining),
                        "need_minutes": {"p50": round(need_p50 or 0), "p80": round(need_p80 or 0)},
                        "booked_minutes": round(booked), "free_minutes": round(free),
                        "finish": {"p50": p50.isoformat() if p50 else None, "p80": p80.isoformat() if p80 else None},
                        "suggestions": suggestions(work, probability, need_p80 or 0, booked, free, keep_rate, zone)})
    # What-ifs re-run the simulation, so only the least likely few get them.
    for entry in sorted((entry for entry in entries if entry["probability"] < SAFE), key=lambda entry: entry["probability"])[:WHAT_IF_TASKS]:
        work = next(item for item in works if item.id == entry["id"])
        entry["suggestions"] += what_ifs(work, works, slots, keep, current, seed, entry["probability"])
    result["tasks"] = entries
    return result


def summary_lines(result: dict) -> list[dict]:
    """Compact facts for answering "will I make it?" questions, in the user's timezone."""
    zone = ZoneInfo(result["timezone"])
    lines = []
    for entry in result["tasks"]:
        finish = entry["finish"]["p80"]
        lines.append({"kind": "forecast", "title": entry["title"], "status": entry["status"],
                      "deadline": _local(datetime.fromisoformat(entry["deadline"]), zone),
                      "chance_on_time": f"{round(entry['probability'] * 100)}%",
                      "likely_finish": _local(datetime.fromisoformat(finish), zone) if finish else "not within two weeks",
                      "advice": next((item["text"] for item in entry["suggestions"] if item["kind"] != "estimate"), None)})
    for item in result["overdue"]:
        lines.append({"kind": "forecast", "title": item["title"], "status": "overdue",
                      "deadline": _local(datetime.fromisoformat(item["deadline"]), zone), "chance_on_time": "0%",
                      "likely_finish": None, "advice": "The deadline has passed."})
    return lines
