"""Adaptive duration estimates from check-ins after FocusOS blocks.

Each check-in gives a ratio actual/planned. Ratios are averaged in log space, so
"took twice as long" and "took half as long" cancel out, and shrunk toward a prior:

    mean = (sum(log ratios) + PRIOR_WEIGHT * prior) / (n + PRIOR_WEIGHT)

With few check-ins the prior (no correction, or the user's overall habit for a
project) dominates; with many, the data does. Only aggregates are used: no model
is trained and nothing leaves the database except these numbers.
"""
import math
from dataclasses import dataclass

from focusos_api.database import scoped_client

PRIOR_WEIGHT = 3.0        # pseudo check-ins at the prior mean
PRIOR_SPREAD = 0.25       # prior log-ratio spread (about ±28%)
MIN_SESSIONS = 5          # below this the factor is shown but not applied to scheduling
MIN_EFFECT = 0.1          # ignore corrections smaller than ±10%
FACTOR_RANGE = (0.5, 3.0)
HISTORY = 200


@dataclass(frozen=True)
class Estimate:
    factor: float     # multiply a planned duration by this
    low: float        # typical range of a single session's ratio
    high: float
    sessions: int
    scope: str        # "overall" or "project"

    def confident(self) -> bool:
        return self.sessions >= MIN_SESSIONS and abs(self.factor - 1) >= MIN_EFFECT

    def as_dict(self) -> dict:
        return {"factor": round(self.factor, 2), "low": round(self.low, 2), "high": round(self.high, 2),
                "sessions": self.sessions, "scope": self.scope, "applied": self.confident()}


def _clamp(value: float) -> float:
    return min(FACTOR_RANGE[1], max(FACTOR_RANGE[0], value))


def shrunk(logs: list[float], prior: float, scope: str) -> Estimate:
    n = len(logs)
    mean = (sum(logs) + PRIOR_WEIGHT * prior) / (n + PRIOR_WEIGHT)
    spread = math.sqrt((sum((value - mean) ** 2 for value in logs) + PRIOR_WEIGHT * PRIOR_SPREAD ** 2) / (n + PRIOR_WEIGHT))
    return Estimate(_clamp(math.exp(mean)), _clamp(math.exp(mean - spread)), _clamp(math.exp(mean + spread)), n, scope)


def log_ratio(row: dict) -> float | None:
    """Only finished or partly finished sessions say how long work takes; skipped blocks do not."""
    planned, actual = row.get("planned_minutes"), row.get("actual_minutes")
    if row.get("outcome") not in ("done", "partial") or not isinstance(planned, int) or not isinstance(actual, int):
        return None
    if planned <= 0 or actual <= 0:
        return None
    return math.log(actual / planned)


def estimate_factors(rows: list[dict]) -> dict:
    """Overall factor plus one per project, each project shrunk toward the overall habit."""
    usable = [(row.get("project_id"), value) for row in rows if (value := log_ratio(row)) is not None]
    overall = shrunk([value for _, value in usable], 0.0, "overall")
    prior = math.log(overall.factor)
    projects: dict[str, list[float]] = {}
    for project, value in usable:
        if project: projects.setdefault(str(project), []).append(value)
    return {"overall": overall, "projects": {key: shrunk(values, prior, "project") for key, values in projects.items()}}


def factor_for(factors: dict, project_id: str | None) -> Estimate:
    return factors["projects"].get(str(project_id)) if project_id and str(project_id) in factors["projects"] else factors["overall"]


def adjusted_minutes(minutes: int, estimate: Estimate) -> int:
    """A corrected duration rounded to 5 minutes, inside the planner's 15-480 range."""
    return max(15, min(480, int(5 * round(minutes * estimate.factor / 5))))


def load_factors(token: str) -> dict:
    with scoped_client(token) as (owner, client):
        rows = (client.table("work_sessions").select("project_id,planned_minutes,actual_minutes,outcome")
                .eq("user_id", owner).order("created_at", desc=True).limit(HISTORY).execute().data)
    return estimate_factors(rows if isinstance(rows, list) else [])


def summary(token: str) -> dict:
    factors = load_factors(token)
    return {"overall": factors["overall"].as_dict(),
            "projects": {key: value.as_dict() for key, value in factors["projects"].items()},
            "min_sessions": MIN_SESSIONS}
