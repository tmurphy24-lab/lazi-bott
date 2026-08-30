"""
F2: Scheduler — run bots on a cron schedule (e.g. every morning at 9am).

Public API:
    add_schedule(name, persona, engine, provider, cron_expr) -> Schedule
    list_schedules() -> List[Schedule]
    remove_schedule(name) -> bool
    is_due(schedule, now=None) -> bool  (pure function)
    next_run(schedule, now=None) -> datetime  (pure function)
    parse_cron(expr) -> dict  (rough parser: minute hour dom mon dow)

Uses stdlib only (no APScheduler). The app can poll is_due() from a QTimer.
"""

from __future__ import annotations
import json
import logging
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

SCHEDULES_DIR = Path("runs/schedules")
SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)
SCHEDULES_PATH = SCHEDULES_DIR / "schedules.json"


@dataclass
class Schedule:
    name: str
    persona: str
    engine: str
    provider: str
    mode: str
    cron_expr: str           # e.g. "0 9 * * 1-5" (9am Mon-Fri)
    enabled: bool = True
    last_run: Optional[str] = None
    next_run: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Schedule":
        return cls(**d)


def _load_all() -> List[Schedule]:
    if not SCHEDULES_PATH.exists():
        return []
    try:
        data = json.loads(SCHEDULES_PATH.read_text(encoding="utf-8"))
        return [Schedule.from_dict(d) for d in data]
    except (json.JSONDecodeError, OSError):
        return []


def _save_all(schedules: List[Schedule]) -> None:
    SCHEDULES_PATH.write_text(
        json.dumps([s.to_dict() for s in schedules], indent=2),
        encoding="utf-8",
    )


def add_schedule(name: str, persona: str, engine: str, provider: str,
                  mode: str, cron_expr: str, enabled: bool = True) -> Schedule:
    """Add or replace a schedule by name."""
    schedules = _load_all()
    # remove existing with same name
    schedules = [s for s in schedules if s.name != name]
    s = Schedule(name=name, persona=persona, engine=engine, provider=provider,
                 mode=mode, cron_expr=cron_expr, enabled=enabled)
    schedules.append(s)
    _save_all(schedules)
    return s


def list_schedules() -> List[Schedule]:
    return _load_all()


def remove_schedule(name: str) -> bool:
    schedules = _load_all()
    new = [s for s in schedules if s.name != name]
    if len(new) == len(schedules):
        return False
    _save_all(new)
    return True


def set_enabled(name: str, enabled: bool) -> Optional[Schedule]:
    schedules = _load_all()
    for s in schedules:
        if s.name == name:
            s.enabled = enabled
            _save_all(schedules)
            return s
    return None


# --- pure cron helpers ---

def parse_cron(expr: str) -> Dict[str, Any]:
    """Parse a 5-field cron expression: minute hour day-of-month month day-of-week.
    Supports *, N, N-M, N,M, */N.
    """
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"Cron must have 5 fields, got {len(parts)}: {expr!r}")
    return {
        "minute":  _parse_field(parts[0], 0, 59),
        "hour":    _parse_field(parts[1], 0, 23),
        "dom":     _parse_field(parts[2], 1, 31),
        "month":   _parse_field(parts[3], 1, 12),
        "dow":     _parse_field(parts[4], 0, 6),
    }


def _parse_field(field: str, lo: int, hi: int) -> List[int]:
    """Parse a single cron field, returning a sorted list of valid integer values."""
    if field == "*":
        return list(range(lo, hi + 1))
    if field.startswith("*/"):
        step = int(field[2:])
        return list(range(lo, hi + 1, step))
    if "-" in field:
        a, b = field.split("-", 1)
        return list(range(int(a), int(b) + 1))
    if "," in field:
        out = []
        for p in field.split(","):
            if "-" in p:
                a, b = p.split("-", 1)
                out.extend(range(int(a), int(b) + 1))
            else:
                out.append(int(p))
        return sorted(set(out))
    return [int(field)]


def _matches(field_values: List[int], target: int) -> bool:
    return target in field_values


def is_due(schedule: Schedule, now: Optional[datetime] = None,
            last_run: Optional[datetime] = None) -> bool:
    """Pure: True if the schedule is due to run *right now* given the last_run."""
    if not schedule.enabled:
        return False
    now = now or datetime.now()
    last = last_run
    if last is None and schedule.last_run:
        try:
            last = datetime.fromisoformat(schedule.last_run.replace("Z", ""))
        except ValueError:
            last = None
    if last and last >= now.replace(hour=now.hour, minute=now.minute, second=now.second, microsecond=0):
        return False  # already ran this minute
    try:
        cron = parse_cron(schedule.cron_expr)
    except ValueError:
        return False
    # dow in Python: Mon=0..Sun=6; cron: 0=Sun..6=Sat. Convert cron dow to python dow.
    cron_dow = cron["dow"]
    py_dow = [0 if d == 6 else d + 1 for d in cron_dow]  # cron Sun(0) -> py Mon(0) etc.
    if 0 in cron_dow:
        py_dow.append(0)  # cron Sun=0 already in py=0
    return (now.minute in cron["minute"]
            and now.hour in cron["hour"]
            and now.day in cron["dom"]
            and now.month in cron["month"]
            and now.weekday() in py_dow)


def next_run(schedule: Schedule, now: Optional[datetime] = None) -> Optional[datetime]:
    """Return the next datetime the schedule should fire, or None if cron invalid."""
    if not schedule.enabled:
        return None
    now = now or datetime.now()
    try:
        cron = parse_cron(schedule.cron_expr)
    except ValueError:
        return None
    # brute force search: scan next 8 days, minute by minute
    cron_dow_py = set()
    for d in cron["dow"]:
        if d == 0:
            cron_dow_py.add(6)  # cron Sun=0 -> py weekday=6
        else:
            cron_dow_py.add(d - 1)  # cron Mon=1..Sat=6 -> py 0..5
    candidate = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(8 * 24 * 60):
        if (candidate.minute in cron["minute"]
                and candidate.hour in cron["hour"]
                and candidate.day in cron["dom"]
                and candidate.month in cron["month"]
                and candidate.weekday() in cron_dow_py):
            return candidate
        candidate += timedelta(minutes=1)
    return None
