"""Place several tasks at once by minimizing one weighted cost, instead of first-fit per task.

Model (all times on a 15-minute grid inside the free intervals of the Calendar snapshot):
  hard  - each task gets one contiguous block of its full duration, inside free time,
          ending by its deadline, with a 5-minute gap between FocusOS blocks;
  soft  - cost = priority weight x hours from the window start  (important work earlier)
               + deadline pressure when a block ends close to its deadline
               + a small penalty for back-to-back blocks (room to breathe).
Search is depth-first branch-and-bound: the most constrained task first, cheapest
candidates first, pruning any branch whose cost plus each remaining task's cheapest
placement cannot beat the best plan found. Node and time limits keep it inside a
serverless request; if no plan is found the caller falls back to the greedy planner.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import time

GRID_MINUTES = 15
BUFFER_MINUTES = 5
MAX_CANDIDATES = 200
NODE_LIMIT = 60_000
TIME_LIMIT_SECONDS = 2.0
PRIORITY_WEIGHT = {"high": 3.0, "normal": 2.0, "low": 1.0}
DEADLINE_COMFORT_HOURS = 4.0   # ending closer than this to a deadline costs extra
DEADLINE_WEIGHT = 2.0
TIGHT_GAP_MINUTES = 15         # blocks closer than this count as back-to-back
TIGHT_PENALTY = 0.5


@dataclass(frozen=True)
class Job:
    ref: str
    minutes: int
    deadline: datetime | None
    priority: str = "normal"


@dataclass(frozen=True)
class Placement:
    ref: str
    start: datetime
    end: datetime
    cost: float


@dataclass(frozen=True)
class Solution:
    placements: tuple[Placement, ...]
    cost: float
    optimal: bool      # False when a limit stopped the search early
    nodes: int


def _aligned(moment: datetime) -> datetime:
    epoch = int(moment.timestamp())
    step = GRID_MINUTES * 60
    return datetime.fromtimestamp(-(-epoch // step) * step, tz=timezone.utc)


def placement_cost(job: Job, start: datetime, end: datetime, origin: datetime) -> float:
    cost = PRIORITY_WEIGHT.get(job.priority, 2.0) * (start - origin).total_seconds() / 3600
    if job.deadline is not None:
        slack = (job.deadline - end).total_seconds() / 3600
        cost += DEADLINE_WEIGHT * max(0.0, DEADLINE_COMFORT_HOURS - slack)
    return cost


def candidates(job: Job, free: list[tuple[datetime, datetime]], origin: datetime) -> list[Placement]:
    """Feasible starts: each free interval's start, then every grid point that still fits."""
    length = timedelta(minutes=job.minutes)
    found: list[Placement] = []
    for low, high in free:
        if job.deadline is not None:
            high = min(high, job.deadline)
        starts = [low]
        point = _aligned(low)
        while point + length <= high:
            if point > low: starts.append(point)
            point += timedelta(minutes=GRID_MINUTES)
        for start in starts:
            end = start + length
            if end <= high:
                found.append(Placement(job.ref, start, end, placement_cost(job, start, end, origin)))
        if len(found) >= MAX_CANDIDATES:
            break
    return sorted(found[:MAX_CANDIDATES], key=lambda item: (item.cost, item.start))


def _pair_penalty(a: Placement, b: Placement) -> float | None:
    """None when two blocks overlap (or lack the buffer); otherwise the soft penalty."""
    gap = max((b.start - a.end).total_seconds(), (a.start - b.end).total_seconds()) / 60
    if gap < BUFFER_MINUTES:
        return None
    return TIGHT_PENALTY if gap < TIGHT_GAP_MINUTES else 0.0


def optimize(jobs: list[Job], free: list[tuple[datetime, datetime]], origin: datetime, *,
             node_limit: int = NODE_LIMIT, time_limit: float = TIME_LIMIT_SECONDS) -> Solution | None:
    options = {job.ref: candidates(job, free, origin) for job in jobs}
    if any(not values for values in options.values()):
        return None
    order = sorted(jobs, key=lambda job: (len(options[job.ref]), job.ref))
    floor = [options[job.ref][0].cost for job in order]
    remaining_floor = [sum(floor[index:]) for index in range(len(order) + 1)]
    best: list = [None, float("inf")]
    nodes = 0
    stopped = False
    deadline = time.monotonic() + time_limit

    def search(depth: int, chosen: list[Placement], cost: float) -> None:
        nonlocal nodes, stopped
        if stopped: return
        if depth == len(order):
            if cost < best[1]: best[0], best[1] = tuple(chosen), cost
            return
        for option in options[order[depth].ref]:
            nodes += 1
            if nodes > node_limit or (nodes % 512 == 0 and time.monotonic() > deadline):
                stopped = True
                return
            if cost + option.cost + remaining_floor[depth + 1] >= best[1]:
                break  # candidates are sorted by cost, so later ones cannot do better
            extra = 0.0
            for other in chosen:
                penalty = _pair_penalty(option, other)
                if penalty is None: break
                extra += penalty
            else:
                chosen.append(option)
                search(depth + 1, chosen, cost + option.cost + extra)
                chosen.pop()
                if stopped: return

    search(0, [], 0.0)
    if best[0] is None:
        return None
    placements = tuple(sorted(best[0], key=lambda item: item.start))
    return Solution(placements, round(best[1], 4), not stopped, nodes)


def greedy(jobs: list[Job], free: list[tuple[datetime, datetime]], origin: datetime) -> Solution | None:
    """Earliest deadline first, earliest fitting slot: the baseline the optimizer is compared with."""
    chosen: list[Placement] = []
    for job in sorted(jobs, key=lambda job: (job.deadline or datetime.max.replace(tzinfo=timezone.utc), job.ref)):
        options = sorted(candidates(job, free, origin), key=lambda item: item.start)
        pick = next((option for option in options if all(_pair_penalty(option, other) is not None for other in chosen)), None)
        if pick is None:
            return None
        chosen.append(pick)
    cost = sum(item.cost for item in chosen) + sum(_pair_penalty(a, b) or 0.0 for i, a in enumerate(chosen) for b in chosen[i + 1:])
    return Solution(tuple(sorted(chosen, key=lambda item: item.start)), round(cost, 4), True, len(chosen))


def reason(job: Job, placement: Placement, zone) -> str:
    """One short line explaining a block, for the plan the user sees."""
    parts = [f"{job.priority} priority"]
    if job.deadline is not None:
        slack = (job.deadline - placement.end).total_seconds() / 3600
        parts.append(f"due {job.deadline.astimezone(zone):%a %d %b %H:%M}"
                     + (" (tight)" if slack < DEADLINE_COMFORT_HOURS else ""))
    else:
        parts.append("no deadline")
    return ("Optimized: " + ", ".join(parts) + ".")[:160]
