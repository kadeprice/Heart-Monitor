"""Google Pixel Watch / Fitbit "ECG - Heart Rhythm Assessment" PDF reports."""
from __future__ import annotations

import re
from datetime import datetime

import numpy as np

from . import ParseError, Recording
from .pdfpaths import polylines

RESULT_WORDS = re.compile(
    r"sinus rhythm|atrial fibrillation|afib|inconclusive|unclassified|high heart rate|low heart rate|"
    r"irregular|bradycardia|tachycardia|unreadable",
    re.I,
)


def matches(text: str) -> bool:
    return "Heart Rhythm Assessment" in text or "Pixel Watch" in text or "Fitbit" in text


def parse(reader, text: str) -> Recording:
    m = re.search(r"Recorded on\s+([A-Za-z]+ \d{1,2}, \d{4},? \d{1,2}:\d{2}\s*[AP]M)", text)
    if not m:
        raise ParseError("Pixel/Fitbit PDF: no 'Recorded on' date found.")
    stamp = m.group(1).replace(",", "")
    recorded_at = datetime.strptime(stamp, "%B %d %Y %I:%M %p")

    lines = [l.strip() for l in text.splitlines() if l.strip()]
    determination = next((l for l in lines if RESULT_WORDS.search(l) and len(l) < 60
                          and "detect" not in l.lower()), "Unknown")
    hr = re.search(r"Average\s*\n?\s*(\d+)\s*bpm", text, re.I)
    reported_hr = int(hr.group(1)) if hr else None

    sc = re.search(r"(\d+(?:\.\d+)?)\s*mm/s,\s*(\d+(?:\.\d+)?)\s*mm/mV,\s*(\d+(?:\.\d+)?)\s*Hz", text)
    mm_s, mm_mv, rate = (float(sc.group(1)), float(sc.group(2)), float(sc.group(3))) if sc else (25.0, 10.0, 250.0)

    hw = re.search(r"Hardware:\s*\[([^\]]+)\]", text)
    device = hw.group(1).strip() if hw else "Pixel Watch / Fitbit"

    # Each strip is a Form XObject drawn in page order; the longest polyline in each is the trace.
    chunks: list[np.ndarray] = []
    for page in reader.pages:
        res = page.get("/Resources") or {}
        xobjs = res.get("/XObject") or {}
        contents = page.get_contents()
        if contents is None:
            continue
        order = re.findall(rb"/([^\s/]+)\s+Do", contents.get_data())
        for name in order:
            ref = xobjs.get("/" + name.decode("latin1"))
            if ref is None:
                continue
            xo = ref.get_object()
            if xo.get("/Subtype") != "/Form":
                continue
            lines_ = [p for p in polylines(xo.get_data()) if len(p) > 100]
            if not lines_:
                continue
            a = np.asarray(max(lines_, key=len).points)
            dx = float(np.median(np.diff(a[:, 0])))
            units_per_mm = dx / (mm_s / rate)
            # Form space grows downward too: invert so positive = up.
            chunks.append(-(a[:, 1] - np.median(a[:, 1])) / (mm_mv * units_per_mm))

    if not chunks:
        raise ParseError("Pixel/Fitbit PDF: no ECG trace found.")
    lead = np.concatenate(chunks).astype(np.float32)
    return Recording("pixel", device, recorded_at, determination, reported_hr, rate, {"I": lead})
