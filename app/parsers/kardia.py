"""AliveCor Kardia "EKG Recording" PDF exports (KardiaMobile, 6L, Card)."""
from __future__ import annotations

import re
from datetime import datetime

import numpy as np

from . import ParseError, Recording
from .pdfpaths import polylines

MM = 72 / 25.4            # PDF points per millimetre
BLACK = (0.0, 0.0, 0.0)
SIX_LEADS = ["I", "II", "III", "aVR", "aVL", "aVF"]
KNOWN_RATES = (125, 250, 300, 500, 512, 1000)


def matches(text: str) -> bool:
    return "AliveCor" in text or "Kardia Determination" in text


def _after(text: str, label: str) -> str | None:
    lines = [l.strip() for l in text.splitlines()]
    for i, line in enumerate(lines):
        if line.startswith(label):
            rest = line[len(label):].strip(" :")
            if rest:
                return rest
            for nxt in lines[i + 1:]:
                if nxt:
                    return nxt
    return None


def _scale(text: str) -> tuple[float, float]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*mm/s,\s*(\d+(?:\.\d+)?)\s*mm/mV", text)
    return (float(m.group(1)), float(m.group(2))) if m else (25.0, 10.0)


def parse(reader, text: str) -> Recording:
    when = _after(text, "Recorded on")
    if not when:
        raise ParseError("Kardia PDF: no 'Recorded on' date found.")
    when = when.split("\n")[0].strip()
    recorded_at = None
    for fmt in ("%A, %B %d, %Y, %I:%M %p", "%B %d, %Y, %I:%M %p", "%A, %B %d, %Y %I:%M %p"):
        try:
            recorded_at = datetime.strptime(when, fmt)
            break
        except ValueError:
            pass
    if recorded_at is None:
        raise ParseError(f"Kardia PDF: couldn't understand date '{when}'.")

    hr_txt = _after(text, "Heart Rate") or ""
    m = re.search(r"(\d+)\s*BPM", hr_txt, re.I)
    reported_hr = int(m.group(1)) if m else None
    determination = (_after(text, "Kardia Determination") or "Unknown").strip()

    mm_s, mm_mv = _scale(text)
    six_lead = "6L" in text or "aVF" in text
    lead_names = SIX_LEADS if six_lead else ["I"]

    chunks: dict[str, list[np.ndarray]] = {n: [] for n in lead_names}
    dxs: list[float] = []
    for page in reader.pages[1:]:
        contents = page.get_contents()
        if contents is None:
            continue
        rows = [p for p in polylines(contents.get_data()) if p.color == BLACK and len(p) > 50]
        if not rows:
            continue
        rows.sort(key=lambda p: float(np.median([q[1] for q in p.points])))  # top of page first
        if six_lead:
            if len(rows) % 6:
                raise ParseError(f"Kardia PDF: expected 6 lead traces per page, found {len(rows)}.")
            groups = [rows[i:i + 6] for i in range(0, len(rows), 6)]
        else:
            groups = [[r] for r in rows]
        for g in groups:
            for name, row in zip(lead_names, g):
                a = np.asarray(row.points)
                dxs.append(float(np.median(np.diff(a[:, 0]))))
                base = np.median(a[:, 1])
                # Kardia's page coordinates grow downward, so up on paper = smaller y.
                chunks[name].append((base - a[:, 1]) / (mm_mv * MM))

    if not dxs:
        raise ParseError("Kardia PDF: no ECG trace found.")
    raw_rate = mm_s * MM / float(np.median(dxs))
    rate = min(KNOWN_RATES, key=lambda r: abs(r - raw_rate))
    if abs(rate - raw_rate) / rate > 0.05:
        rate = round(raw_rate, 1)

    leads = {n: np.concatenate(c).astype(np.float32) for n, c in chunks.items() if c}
    device = "KardiaMobile 6L" if six_lead else "KardiaMobile"
    return Recording("kardia", device, recorded_at, determination, reported_hr, float(rate), leads)
