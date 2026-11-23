"""SQLite storage. One file under DATA_DIR; signals stored as compressed float32 blobs."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

import numpy as np

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
DB_PATH = DATA_DIR / "heart.db"
FILES_DIR = DATA_DIR / "files"

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    id            INTEGER PRIMARY KEY,
    sha256        TEXT UNIQUE NOT NULL,
    filename      TEXT,
    source        TEXT NOT NULL,
    device        TEXT,
    recorded_at   TEXT NOT NULL,
    imported_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    determination TEXT,
    reported_hr   INTEGER,
    sample_rate   REAL NOT NULL,
    duration_s    REAL,
    lead_names    TEXT NOT NULL,
    signals       BLOB NOT NULL,
    metrics       TEXT,
    notes         TEXT DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS recordings_when ON recordings(source, recorded_at);

CREATE TABLE IF NOT EXISTS symptoms (
    id          INTEGER PRIMARY KEY,
    occurred_at TEXT NOT NULL,
    kind        TEXT NOT NULL,
    severity    INTEGER,
    duration_min REAL,
    activity    TEXT DEFAULT '',
    notes       TEXT DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""


def init() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    with conn() as c:
        c.executescript(SCHEMA)


@contextmanager
def conn():
    with _lock:
        c = sqlite3.connect(DB_PATH)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()


def pack_signals(leads: dict[str, np.ndarray]) -> bytes:
    buf = io.BytesIO()
    np.savez_compressed(buf, **{k: np.asarray(v, np.float32) for k, v in leads.items()})
    return buf.getvalue()


def unpack_signals(blob: bytes) -> dict[str, np.ndarray]:
    with np.load(io.BytesIO(blob)) as z:
        return {k: z[k] for k in z.files}


def row_to_summary(r: sqlite3.Row) -> dict:
    m = json.loads(r["metrics"] or "{}")
    return {
        "id": r["id"],
        "source": r["source"],
        "device": r["device"],
        "recorded_at": r["recorded_at"],
        "imported_at": r["imported_at"],
        "determination": r["determination"],
        "reported_hr": r["reported_hr"],
        "duration_s": r["duration_s"],
        "leads": json.loads(r["lead_names"]),
        "filename": r["filename"],
        "notes": r["notes"] or "",
        "hr_mean": m.get("hr_mean"),
        "hr_min": m.get("hr_min"),
        "hr_max": m.get("hr_max"),
        "rmssd_ms": m.get("rmssd_ms"),
        "early_beats": len(m.get("early_beats", [])),
        "pauses": len(m.get("pauses", [])),
        "quality": m.get("quality"),
        "flags": sum(1 for o in m.get("observations", []) if o["level"] == "flag"),
    }
