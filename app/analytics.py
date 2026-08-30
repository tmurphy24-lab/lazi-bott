"""
F3: Analytics — dashboard stats from the JobTracker.

Public API:
    compute_stats(persona=None) -> Stats
    by_engine(persona=None) -> dict[str, dict]
    by_week(persona=None) -> dict[str, dict]
    by_company(persona=None) -> dict[str, int]  (top N)
"""

from __future__ import annotations
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from .job_tracker import list_applications

logger = logging.getLogger(__name__)


@dataclass
class Stats:
    total: int
    applied: int
    rejected: int
    interview: int
    offer: int
    withdrawn: int
    response_rate: float       # (interview + offer) / applied
    offer_rate: float          # offer / applied
    by_engine: Dict[str, int]   = field(default_factory=dict)
    by_week: Dict[str, int]    = field(default_factory=dict)
    top_companies: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def compute_stats(persona: Optional[str] = None) -> Stats:
    apps = list_applications(persona=persona)
    total = len(apps)
    by_status = Counter(a.status for a in apps)
    applied  = by_status.get("applied", 0)
    rejected = by_status.get("rejected", 0)
    interview= by_status.get("interview", 0)
    offer    = by_status.get("offer", 0)
    withdrawn= by_status.get("withdrawn", 0)
    denom = max(1, applied)
    return Stats(
        total=total,
        applied=applied,
        rejected=rejected,
        interview=interview,
        offer=offer,
        withdrawn=withdrawn,
        response_rate=round((interview + offer) / denom, 3),
        offer_rate=round(offer / denom, 3),
        by_engine=by_engine(persona=persona),
        by_week=by_week(persona=persona),
        top_companies=dict(Counter(a.company for a in apps).most_common(10)),
    )


def by_engine(persona: Optional[str] = None) -> Dict[str, int]:
    apps = list_applications(persona=persona)
    out: Dict[str, int] = defaultdict(int)
    for a in apps:
        if a.engine:
            out[a.engine] += 1
    return dict(out)


def by_week(persona: Optional[str] = None) -> Dict[str, int]:
    """Return ISO-week -> count of applications, sorted by week."""
    apps = list_applications(persona=persona)
    out: Dict[str, int] = defaultdict(int)
    for a in apps:
        try:
            dt = datetime.fromisoformat(a.applied_at.replace("Z", ""))
        except ValueError:
            continue
        year, week, _ = dt.isocalendar()
        out[f"{year}-W{week:02d}"] += 1
    return dict(sorted(out.items()))


def by_company(persona: Optional[str] = None, top: int = 10) -> Dict[str, int]:
    apps = list_applications(persona=persona)
    return dict(Counter(a.company for a in apps).most_common(top))
