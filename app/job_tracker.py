"""
F1: JobTracker — record every job applied to with status + export to CSV.

Public API:
    record_application(persona, job, status="applied", notes="")
    list_applications(persona=None) -> List[Application]
    update_status(app_id, new_status, notes="")
    export_csv(persona=None) -> str (CSV content)
"""

from __future__ import annotations
import csv
import io
import json
import logging
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

TRACKER_DIR = Path("runs/tracker")
TRACKER_DIR.mkdir(parents=True, exist_ok=True)
TRACKER_PATH = TRACKER_DIR / "applications.jsonl"

VALID_STATUSES = {"applied", "rejected", "interview", "offer", "withdrawn"}


@dataclass
class Application:
    id: str
    persona: str
    title: str
    company: str
    link: str
    status: str
    applied_at: str
    last_updated: str
    notes: str = ""
    engine: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Application":
        return cls(**d)


def record_application(persona: str, job: dict, status: str = "applied",
                        notes: str = "", engine: str = "") -> Application:
    """Record a new job application."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}. Must be one of {VALID_STATUSES}")
    now = datetime.utcnow().isoformat() + "Z"
    app = Application(
        id=str(uuid.uuid4())[:12],
        persona=persona,
        title=job.get("title", ""),
        company=job.get("company", ""),
        link=job.get("link", ""),
        status=status,
        applied_at=now,
        last_updated=now,
        notes=notes,
        engine=engine,
    )
    with open(TRACKER_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(app.to_dict()) + "\n")
    logger.info("Recorded application %s for %s @ %s", app.id, app.title, app.company)
    return app


def list_applications(persona: Optional[str] = None,
                       status: Optional[str] = None) -> List[Application]:
    """Return all applications, optionally filtered by persona and/or status."""
    if not TRACKER_PATH.exists():
        return []
    out = []
    with open(TRACKER_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if persona and d.get("persona") != persona:
                continue
            if status and d.get("status") != status:
                continue
            out.append(Application.from_dict(d))
    return out


def update_status(app_id: str, new_status: str, notes: str = "") -> Optional[Application]:
    """Update an application status. Rewrites the file."""
    if new_status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {new_status}. Must be one of {VALID_STATUSES}")
    if not TRACKER_PATH.exists():
        return None
    rows = []
    found: Optional[Application] = None
    with open(TRACKER_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            app = Application.from_dict(d)
            if app.id == app_id:
                app.status = new_status
                app.last_updated = datetime.utcnow().isoformat() + "Z"
                if notes:
                    app.notes = notes
                found = app
            rows.append(app.to_dict())
    with open(TRACKER_PATH, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return found


def delete_application(app_id: str) -> bool:
    """Remove an application from the tracker."""
    if not TRACKER_PATH.exists():
        return False
    rows = []
    found = False
    with open(TRACKER_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("id") == app_id:
                found = True
                continue
            rows.append(d)
    with open(TRACKER_PATH, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return found


def export_csv(persona: Optional[str] = None) -> str:
    """Return all applications as a CSV string."""
    apps = list_applications(persona=persona)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[
        "id", "persona", "title", "company", "link",
        "status", "engine", "applied_at", "last_updated", "notes"
    ])
    writer.writeheader()
    for a in apps:
        writer.writerow(a.to_dict())
    return buf.getvalue()
