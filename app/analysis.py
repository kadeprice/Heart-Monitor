"""Beat detection, rhythm metrics and plain-language observations for one ECG lead.

This is a personal tracking aid, not a diagnostic tool. Every observation is
phrased as something to notice and discuss with a clinician.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, filtfilt, find_peaks, medfilt

ANALYSIS_VERSION = 1


def _band(x: np.ndarray, fs: float, lo: float, hi: float) -> np.ndarray:
    b, a = butter(2, [lo / (fs / 2), min(hi / (fs / 2), 0.99)], "band")
    return filtfilt(b, a, x)


def _low(x: np.ndarray, fs: float, hi: float) -> np.ndarray:
    b, a = butter(2, hi / (fs / 2), "low")
    return filtfilt(b, a, x)


def _intervals(mask: np.ndarray, fs: float) -> list[list[float]]:
    out, start = [], None
    for i, v in enumerate(np.append(mask, False)):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append([round(start / fs, 2), round(i / fs, 2)])
            start = None
    return out


def find_artifacts(x: np.ndarray, fs: float) -> np.ndarray:
    """Boolean mask of samples spoiled by movement or poor contact."""
    n = len(x)
    mask = np.zeros(n, bool)
    if n < fs:
        return mask
    slow = _low(x, fs, 1.5)                      # baseline wander; QRS spikes mostly filtered out
    mask |= np.abs(slow - np.median(slow)) > 0.8
    mask |= np.abs(x - np.median(x)) > 4.0       # clipping / huge spikes
    # flat line (lost contact): <0.02 mV peak-to-peak over 0.5 s
    w = int(0.5 * fs)
    for s in range(0, n - w, w // 2):
        if np.ptp(x[s:s + w]) < 0.02:
            mask[s:s + w] = True
    mask[: int(0.5 * fs)] |= np.abs(slow[: int(0.5 * fs)]) > 0.4   # start-up settling
    # pad each region by 0.4 s so half-spoiled beats at the edges are dropped too
    pad = int(0.4 * fs)
    idx = np.flatnonzero(mask)
    for i in idx:
        mask[max(0, i - pad): i + pad] = True
    return mask


def detect_beats(x: np.ndarray, fs: float, artifact: np.ndarray | None = None) -> np.ndarray:
    """R-peak sample indices (Pan-Tompkins style energy detector + local refinement)."""
    if len(x) < 2 * fs:
        return np.array([], int)
    bp = _band(x, fs, 5, 15)
    energy = np.convolve(np.gradient(bp) ** 2, np.ones(int(0.15 * fs)) / int(0.15 * fs), "same")
    good = energy if artifact is None or artifact.all() else energy[~artifact]
    thr = 0.3 * np.percentile(good, 98)
    cand, _ = find_peaks(energy, height=thr, distance=int(0.25 * fs))

    # Search back for beats missed in long gaps with a lower threshold.
    if len(cand) > 3:
        rr_med = np.median(np.diff(cand))
        extra = []
        for a, b in zip(cand[:-1], cand[1:]):
            if b - a > 1.6 * rr_med:
                seg = energy[a + int(0.25 * fs): b - int(0.25 * fs)]
                if len(seg):
                    j = int(np.argmax(seg))
                    if seg[j] > 0.5 * thr:
                        extra.append(a + int(0.25 * fs) + j)
        cand = np.sort(np.concatenate([cand, np.array(extra, int)]))

    # Refine onto the actual R wave in the raw signal, using the dominant QRS polarity.
    base = medfilt(x.astype(float), int(0.2 * fs) | 1)
    centred = x - base
    win = int(0.08 * fs)
    def local(i: int) -> slice:
        return slice(max(0, i - win), min(len(x), i + win))
    pol = np.sign(np.median([centred[local(i)][np.argmax(np.abs(centred[local(i)]))] for i in cand])) if len(cand) else 1
    pol = pol or 1
    beats = []
    for i in cand:
        s = local(i)
        beats.append(s.start + int(np.argmax(pol * centred[s])))
    beats = np.unique(np.array(beats, int))
    if len(beats) > 1:  # merge refinements that collapsed onto neighbours
        keep = np.insert(np.diff(beats) > 0.2 * fs, 0, True)
        beats = beats[keep]
    if artifact is not None:
        beats = beats[~artifact[beats]]
    return beats


def analyze(x: np.ndarray, fs: float, reported_hr: int | None = None) -> dict:
    x = np.asarray(x, float)
    artifact = find_artifacts(x, fs)
    beats = detect_beats(x, fs, artifact)
    duration = len(x) / fs
    usable = float((~artifact).sum() / fs)

    # RR intervals only between neighbouring beats with clean signal in between.
    rr_list, rr_at = [], []
    for a, b in zip(beats[:-1], beats[1:]):
        if not artifact[a:b].any():
            rr_list.append((b - a) / fs)
            rr_at.append(int(a))
    rr = np.array(rr_list)

    m: dict = {
        "analysis_version": ANALYSIS_VERSION,
        "duration_s": round(duration, 2),
        "usable_s": round(usable, 1),
        "artifacts": _intervals(artifact, fs),
        "beats": beats.tolist(),
        "beat_count": int(len(beats)),
        "rr_ms": [round(v * 1000) for v in rr],
        "early_beats": [],
        "pauses": [],
    }
    if len(rr) < 4:
        m["quality"] = "poor"
        m["observations"] = _observations(m, reported_hr)
        return m

    hr = 60 / rr
    m.update(
        hr_mean=round(float(60 / rr.mean()), 1),
        hr_min=round(float(hr.min())),
        hr_max=round(float(hr.max())),
        sdnn_ms=round(float(rr.std(ddof=1) * 1000), 1),
        rmssd_ms=round(float(np.sqrt(np.mean(np.diff(rr) ** 2)) * 1000), 1),
        pnn50=round(float(np.mean(np.abs(np.diff(rr)) > 0.05) * 100), 1),
    )

    # Early beats: interval much shorter than its neighbourhood (often followed by a longer one).
    early, pauses = [], []
    for i, v in enumerate(rr):
        ref = np.median(np.delete(rr[max(0, i - 4): i + 5], min(i, 4)))
        if v < 0.8 * ref:
            comp = i + 1 < len(rr) and rr[i + 1] > 1.1 * ref
            early.append({"t": round((rr_at[i] / fs) + v, 2), "rr_ms": round(v * 1000),
                          "expected_ms": round(ref * 1000), "compensatory": bool(comp)})
        if v > 2.0 or v > 1.8 * ref:
            pauses.append({"t": round(rr_at[i] / fs, 2), "rr_ms": round(v * 1000)})
    m["early_beats"], m["pauses"] = early, pauses

    # Irregularity after setting the isolated early beats (and the interval right after) aside.
    skip = set()
    for e in early:
        j = next((k for k, a in enumerate(rr_at) if abs(a / fs + rr[k] - e["t"]) < 0.02), None)
        if j is not None:
            skip.update({j, j + 1})
    base_rr = np.array([v for k, v in enumerate(rr) if k not in skip])
    if len(base_rr) >= 4:
        m["irregularity_cv"] = round(float(base_rr.std() / base_rr.mean()), 3)
        m["irregularity_rmssd_ms"] = round(float(np.sqrt(np.mean(np.diff(base_rr) ** 2)) * 1000), 1)

    m["quality"] = "good" if usable / duration > 0.85 else "fair" if usable / duration > 0.6 else "poor"
    m["observations"] = _observations(m, reported_hr)
    return m


def _observations(m: dict, reported_hr: int | None) -> list[dict]:
    """Short, plain-language notes. level: info | note | flag."""
    obs: list[dict] = []
    if m.get("quality") == "poor":
        obs.append({"level": "note", "title": "Not enough clean signal",
                    "detail": "Too much of this recording was noisy to measure reliably. Rest your arms, "
                              "stay still and keep steady contact for the full 30 seconds."})
        return obs

    hr = int(m["hr_mean"] + 0.5)  # round half up, same as the UI
    if hr < 50:
        obs.append({"level": "flag", "title": f"Slow heart rate ({hr} bpm)",
                    "detail": "Below 50 bpm. Can be normal for fit people or during rest/sleep, but worth "
                              "mentioning to your doctor if you feel dizzy, faint or tired."})
    elif hr < 60:
        obs.append({"level": "info", "title": f"Resting heart rate on the low side ({hr} bpm)",
                    "detail": "50–60 bpm is common at rest, especially if you're active."})
    elif hr <= 100:
        obs.append({"level": "info", "title": f"Heart rate in the normal range ({hr} bpm)",
                    "detail": "60–100 bpm is the typical resting range for adults."})
    else:
        obs.append({"level": "flag", "title": f"Fast heart rate ({hr} bpm)",
                    "detail": "Above 100 bpm at rest. Exercise, caffeine, stress or illness can do this; "
                              "a fast rate during palpitations is useful information for your doctor."})

    if reported_hr and abs(reported_hr - hr) > 8:
        obs.append({"level": "note", "title": "Device and app disagree on heart rate",
                    "detail": f"The device reported {reported_hr} bpm; beat counting here found {hr} bpm. "
                              "Noise or very small/large beats can cause this. Look at the trace."})

    n_early = len(m["early_beats"])
    if n_early:
        per_min = n_early / max(m["usable_s"], 1) * 60
        obs.append({"level": "flag" if n_early >= 3 else "note",
                    "title": f"{n_early} beat{'s' if n_early > 1 else ''} came earlier than expected",
                    "detail": "Early beats (premature atrial or ventricular contractions, PACs/PVCs) are a very "
                              "common cause of the 'skipped' or 'thump' feeling of palpitations. Occasional ones "
                              "are usually harmless; frequent ones "
                              f"(here about {per_min:.0f} per minute) are worth showing your doctor. "
                              "They're marked on the trace."})
    if m["pauses"]:
        longest = max(p["rr_ms"] for p in m["pauses"]) / 1000
        obs.append({"level": "flag", "title": f"Longer-than-expected gap between beats ({longest:.1f} s)",
                    "detail": "A pause can follow an early beat, or be a missed beat. Check the trace; it may "
                              "also be noise. Worth discussing if it happens often or with dizziness."})

    cv = m.get("irregularity_cv")
    if cv is not None:
        if cv > 0.12 and m.get("irregularity_rmssd_ms", 0) > 100:
            obs.append({"level": "flag", "title": "Beat timing looks irregular",
                        "detail": "Even after setting early beats aside, the time between beats varied a lot. "
                                  "An 'irregularly irregular' pattern is what AFib checks look for. This app "
                                  "can't diagnose AFib; compare with your device's own result and talk to your doctor."})
        elif cv > 0.08:
            obs.append({"level": "info", "title": "Some beat-to-beat variation",
                        "detail": "Mild variation, often from breathing (heart rate rises as you breathe in and "
                                  "falls as you breathe out). This is normal, especially when relaxed."})
        else:
            obs.append({"level": "info", "title": "Steady, regular rhythm",
                        "detail": "The time between beats was consistent throughout the clean part of the recording."})

    if m["artifacts"]:
        spans = ", ".join(f"{a:.0f}–{b:.0f}s" for a, b in m["artifacts"][:4])
        obs.append({"level": "info", "title": "Noise excluded",
                    "detail": f"Movement or contact noise at {spans} was left out of the measurements."})
    return obs


DETERMINATIONS: list[tuple[tuple[str, ...], str, str]] = [
    (("atrial fibrillation", "afib"), "flag",
     "The device's algorithm saw an irregular rhythm consistent with atrial fibrillation (AFib). It's a screening "
     "result, not a diagnosis. Share it with your doctor, and seek urgent care if you also have chest pain, "
     "fainting, or shortness of breath."),
    (("pvc",), "note",
     "Normal rhythm with premature ventricular contractions (PVCs): early beats starting in the lower chambers. "
     "Very common and often felt as palpitations; usually benign, but worth discussing if frequent."),
    (("sve", "supraventricular", "ectopy"), "note",
     "Normal rhythm with supraventricular ectopy: early beats starting in the upper chambers (PACs). Common and "
     "often felt as a flutter or skipped beat."),
    (("wide qrs",), "note",
     "Normal rhythm but the main spike (QRS) is wider than usual, which can mean a conduction delay such as a "
     "bundle branch block. Worth showing your doctor if it's new."),
    (("bradycardia", "low heart rate"), "note",
     "Rhythm looks regular but the rate is slow (under 50 bpm). Often normal at rest or in fit people."),
    (("tachycardia", "high heart rate"), "note",
     "Rhythm looks regular but the rate is fast (over 100 bpm, or above the device's analysis limit)."),
    (("unclassified", "inconclusive"), "note",
     "The algorithm couldn't put this into a category. It can be noise, an unusual rhythm, or frequent early "
     "beats. Several of these in a row, especially during symptoms, are worth showing your doctor."),
    (("unreadable", "too short", "no analysis"), "note",
     "Not enough clean signal for the device to analyse. Try again sitting still with arms resting."),
    (("sinus rhythm", "normal"), "info",
     "Normal sinus rhythm: the heartbeat starts in the normal place and the timing is regular. "
     "A normal result during symptoms is reassuring, but a single 30-second recording can miss beats that come and go."),
]


def explain_determination(text: str) -> dict:
    t = (text or "").lower()
    for keys, level, detail in DETERMINATIONS:
        if any(k in t for k in keys):
            return {"level": level, "detail": detail}
    return {"level": "note", "detail": "Result not recognised. See your device's app for its definition."}
