from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("heart")

STATIC = Path(__file__).parent / "static"
IMPORT_DIR = os.environ.get("IMPORT_DIR", "").strip()
IMPORT_INTERVAL = int(os.environ.get("IMPORT_INTERVAL_SECONDS", "60"))
MAX_UPLOAD = 20 * 1024 * 1024


def _watch_folder(stop: threading.Event) -> None:
    """Import any new PDF that appears in IMPORT_DIR (e.g. a synced Google Drive folder).

    Files are never moved or deleted; already-seen files are skipped by content hash.
    """
    folder = Path(IMPORT_DIR)
    seen: set[str] = set()
    log.info("watching %s for new ECG PDFs every %ss", folder, IMPORT_INTERVAL)
    while not stop.is_set():
        try:
            for p in sorted(folder.rglob("*")):
                if p.suffix.lower() != ".pdf" or not p.is_file():
                    continue
                key = f"{p}:{p.stat().st_size}:{p.stat().st_mtime_ns}"
                if key in seen:
                    continue
                data = p.read_bytes()
                if len(data) <= MAX_UPLOAD:
                    res = service.import_pdf(data, p.name)
                    if res["status"] == "error":
                        log.info("skipped %s: %s", p.name, res["message"])
                seen.add(key)
        except Exception:  # noqa: BLE001 - keep the watcher alive
            log.exception("folder import failed")
        stop.wait(IMPORT_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    n = service.reanalyze_stale()
    if n:
        log.info("re-analysed %d recordings with the current algorithm", n)
    stop = threading.Event()
    if IMPORT_DIR and Path(IMPORT_DIR).is_dir():
        threading.Thread(target=_watch_folder, args=(stop,), daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="Heart Monitor", lifespan=lifespan)


# ---------- recordings ----------

@app.post("/api/import")
async def import_files(files: list[UploadFile] = File(...)):
    results = []
    for f in files:
        data = await f.read()
        if len(data) > MAX_UPLOAD:
            results.append({"status": "error", "filename": f.filename, "message": "File too large."})
        elif not data.startswith(b"%PDF"):
            results.append({"status": "error", "filename": f.filename, "message": "Not a PDF."})
        else:
            results.append(service.import_pdf(data, f.filename or "upload.pdf"))
    return {"results": results}


@app.get("/api/recordings")
def list_recordings():
    with db.conn() as c:
        rows = c.execute("SELECT * FROM recordings ORDER BY recorded_at DESC").fetchall()
    return [db.row_to_summary(r) for r in rows]


@app.get("/api/recordings/{rid}")
def get_recording(rid: int):
    d = service.recording_detail(rid)
    if not d:
        raise HTTPException(404)
    return d


@app.get("/api/recordings/{rid}/signal")
def get_signal(rid: int):
    d = service.recording_signal(rid)
    if not d:
        raise HTTPException(404)
    return d


@app.get("/api/recordings/{rid}/pdf")
def get_pdf(rid: int):
    p = db.FILES_DIR / f"{rid}.pdf"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="application/pdf", filename=f"ecg-{rid}.pdf")


class NotesIn(BaseModel):
    notes: str = Field("", max_length=5000)


@app.patch("/api/recordings/{rid}")
def update_recording(rid: int, body: NotesIn):
    with db.conn() as c:
        if not c.execute("UPDATE recordings SET notes=? WHERE id=?", (body.notes, rid)).rowcount:
            raise HTTPException(404)
    return {"ok": True}


@app.delete("/api/recordings/{rid}")
def delete_recording(rid: int):
    with db.conn() as c:
        if not c.execute("DELETE FROM recordings WHERE id=?", (rid,)).rowcount:
            raise HTTPException(404)
    (db.FILES_DIR / f"{rid}.pdf").unlink(missing_ok=True)
    return {"ok": True}


# ---------- symptoms ----------

class SymptomIn(BaseModel):
    occurred_at: datetime | None = None
    kind: str = Field("Palpitations", max_length=80)
    severity: int | None = Field(None, ge=1, le=5)
    duration_min: float | None = Field(None, ge=0)
    activity: str = Field("", max_length=200)
    notes: str = Field("", max_length=5000)


@app.get("/api/symptoms")
def get_symptoms():
    return service.list_symptoms()


@app.post("/api/symptoms")
def add_symptom(s: SymptomIn):
    when = (s.occurred_at or datetime.now()).replace(tzinfo=None, second=0, microsecond=0)
    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO symptoms (occurred_at, kind, severity, duration_min, activity, notes) VALUES (?,?,?,?,?,?)",
            (when.isoformat(timespec="minutes"), s.kind, s.severity, s.duration_min, s.activity, s.notes))
    return {"id": cur.lastrowid}


@app.delete("/api/symptoms/{sid}")
def delete_symptom(sid: int):
    with db.conn() as c:
        if not c.execute("DELETE FROM symptoms WHERE id=?", (sid,)).rowcount:
            raise HTTPException(404)
    return {"ok": True}


# ---------- overview ----------

@app.get("/api/summary")
def get_summary():
    return service.summary()


@app.get("/api/status")
def status():
    return {"import_dir": IMPORT_DIR or None,
            "import_dir_ok": bool(IMPORT_DIR) and Path(IMPORT_DIR).is_dir(),
            "import_interval_s": IMPORT_INTERVAL}


@app.get("/healthz")
def healthz():
    return {"ok": True}


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
