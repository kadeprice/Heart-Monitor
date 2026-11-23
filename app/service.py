"""Import, re-analysis and summary logic shared by the API and the folder watcher."""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timedelta

from . import db
from .analysis import ANALYSIS_VERSION, analyze, explain_determination
from .parsers import ParseError, parse_pdf

log = logging.getLogger("heart")

PRIMARY_LEAD = "I"
SYMPTOM_WINDOW_MIN = 60


def import_pdf(data: bytes, filename: str) -> dict:
    """Parse, analyse and store a report. Returns {status, id?, message}."""
    sha = hashlib.sha256(data).hexdigest()
    with db.conn() as c:
        row = c.execute("SELECT id FROM recordings WHERE sha256=?", (sha,)).fetchone()
    if row:
        return {"status": "duplicate", "id": row["id"], "filename": filename, "message": "Already imported."}
    try:
        rec = parse_pdf(data)
    except ParseError as e:
        return {"status": "error", "filename": filename, "message": str(e)}

    lead = rec.leads.get(PRIMARY_LEAD, next(iter(rec.leads.values())))
    metrics = analyze(lead, rec.sample_rate, rec.reported_hr)
    try:
        with db.conn() as c:
            cur = c.execute(
                """INSERT INTO recordings (sha256, filename, source, device, recorded_at, determination,
                   reported_hr, sample_rate, duration_s, lead_names, signals, metrics)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sha, filename, rec.source, rec.device, rec.recorded_at.isoformat(timespec="minutes"),
                 rec.determination, rec.reported_hr, rec.sample_rate, round(rec.duration_s, 2),
                 json.dumps(list(rec.leads)), db.pack_signals(rec.leads), json.dumps(metrics)),
            )
            rid = cur.lastrowid
    except sqlite3.IntegrityError:
        with db.conn() as c:
            row = c.execute("SELECT id FROM recordings WHERE source=? AND recorded_at=?",
                            (rec.source, rec.recorded_at.isoformat(timespec="minutes"))).fetchone()
        return {"status": "duplicate", "id": row["id"] if row else None, "filename": filename,
                "message": "A recording from that device at that time is already imported."}
    (db.FILES_DIR / f"{rid}.pdf").write_bytes(data)
    log.info("imported %s as #%s (%s %s)", filename, rid, rec.source, rec.recorded_at)
    return {"status": "imported", "id": rid, "filename": filename,
            "message": f"{rec.device}, {rec.recorded_at:%b %d %Y %I:%M %p}: {rec.determination}"}


def reanalyze_stale() -> int:
    """Re-run analysis on recordings analysed by an older algorithm version."""
    n = 0
    with db.conn() as c:
        rows = c.execute("SELECT id, metrics, signals, lead_names, sample_rate, reported_hr FROM recordings").fetchall()
    for r in rows:
        m = json.loads(r["metrics"] or "{}")
        if m.get("analysis_version") == ANALYSIS_VERSION:
            continue
        leads = db.unpack_signals(r["signals"])
        lead = leads.get(PRIMARY_LEAD, next(iter(leads.values())))
        new = analyze(lead, r["sample_rate"], r["reported_hr"])
        with db.conn() as c:
            c.execute("UPDATE recordings SET metrics=? WHERE id=?", (json.dumps(new), r["id"]))
        n += 1
    return n


def recording_detail(rid: int) -> dict | None:
    with db.conn() as c:
        r = c.execute("SELECT * FROM recordings WHERE id=?", (rid,)).fetchone()
    if not r:
        return None
    out = db.row_to_summary(r)
    out["metrics"] = json.loads(r["metrics"] or "{}")
    out["sample_rate"] = r["sample_rate"]
    out["determination_info"] = explain_determination(r["determination"])
    out["nearby_symptoms"] = symptoms_near(r["recorded_at"])
    return out


def recording_signal(rid: int) -> dict | None:
    with db.conn() as c:
        r = c.execute("SELECT signals, sample_rate, metrics FROM recordings WHERE id=?", (rid,)).fetchone()
    if not r:
        return None
    leads = db.unpack_signals(r["signals"])
    m = json.loads(r["metrics"] or "{}")
    return {
        "fs": r["sample_rate"],
        "leads": {k: [round(float(v), 3) for v in arr] for k, arr in leads.items()},
        "beats": m.get("beats", []),
        "early": [e["t"] for e in m.get("early_beats", [])],
        "pauses": m.get("pauses", []),
        "artifacts": m.get("artifacts", []),
    }


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def symptoms_near(recorded_at: str, minutes: int = SYMPTOM_WINDOW_MIN) -> list[dict]:
    t = _parse(recorded_at)
    lo, hi = (t - timedelta(minutes=minutes)).isoformat(), (t + timedelta(minutes=minutes)).isoformat()
    with db.conn() as c:
        rows = c.execute("SELECT * FROM symptoms WHERE occurred_at BETWEEN ? AND ? ORDER BY occurred_at",
                         (lo, hi)).fetchall()
    return [dict(r) for r in rows]


def list_symptoms() -> list[dict]:
    with db.conn() as c:
        syms = [dict(r) for r in c.execute("SELECT * FROM symptoms ORDER BY occurred_at DESC")]
        recs = [(r["id"], r["recorded_at"], r["determination"])
                for r in c.execute("SELECT id, recorded_at, determination FROM recordings")]
    for s in syms:
        t = _parse(s["occurred_at"])
        near = [(abs((_parse(ra) - t).total_seconds()) / 60, rid, ra, det) for rid, ra, det in recs]
        near = sorted(n for n in near if n[0] <= SYMPTOM_WINDOW_MIN)
        s["recordings"] = [{"id": rid, "recorded_at": ra, "determination": det, "minutes_apart": round(mins)}
                           for mins, rid, ra, det in near]
    return syms


def summary() -> dict:
    with db.conn() as c:
        rows = c.execute("SELECT * FROM recordings ORDER BY recorded_at").fetchall()
        n_sym = c.execute("SELECT COUNT(*) FROM symptoms").fetchone()[0]
    recs = [db.row_to_summary(r) for r in rows]
    by_det: dict[str, int] = {}
    for r in recs:
        by_det[r["determination"] or "Unknown"] = by_det.get(r["determination"] or "Unknown", 0) + 1
    hrs = [r["hr_mean"] for r in recs if r["hr_mean"]]
    syms = list_symptoms()
    return {
        "recording_count": len(recs),
        "symptom_count": n_sym,
        "symptoms_with_recording": sum(1 for s in syms if s["recordings"]),
        "by_determination": by_det,
        "by_source": {s: sum(1 for r in recs if r["source"] == s) for s in {r["source"] for r in recs}},
        "hr_avg": round(sum(hrs) / len(hrs), 1) if hrs else None,
        "early_beat_recordings": sum(1 for r in recs if r["early_beats"]),
        "first": recs[0]["recorded_at"] if recs else None,
        "last": recs[-1]["recorded_at"] if recs else None,
        "trend": [{"id": r["id"], "t": r["recorded_at"], "hr": r["hr_mean"], "det": r["determination"],
                   "source": r["source"], "early": r["early_beats"]} for r in recs],
    }
