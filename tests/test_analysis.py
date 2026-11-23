import numpy as np

from app.analysis import analyze, explain_determination


def regular(rate_bpm, duration=30.0, start=0.6):
    step = 60 / rate_bpm
    return list(np.arange(start, duration - 0.4, step))


def test_regular_rhythm(synth):
    m = analyze(synth(regular(70)), 300, reported_hr=70)
    assert abs(m["hr_mean"] - 70) < 1
    assert m["early_beats"] == [] and m["pauses"] == []
    assert m["quality"] == "good"
    titles = [o["title"] for o in m["observations"]]
    assert any("normal range" in t for t in titles)
    assert any("regular" in t.lower() for t in titles)


def test_early_beats_are_flagged(synth):
    beats = regular(60)
    # make beats 10 and 20 arrive 350 ms early (with the usual compensatory pause after)
    beats[10] -= 0.35
    beats[20] -= 0.35
    m = analyze(synth(beats), 300)
    assert len(m["early_beats"]) == 2
    assert all(e["compensatory"] for e in m["early_beats"])
    assert any("earlier than expected" in o["title"] for o in m["observations"])


def test_irregular_rhythm_flagged(synth):
    rng = np.random.default_rng(3)
    t, beats = 0.6, []
    while t < 29.5:
        beats.append(t)
        t += rng.uniform(0.45, 1.1)
    m = analyze(synth(beats), 300)
    assert any(o["title"] == "Beat timing looks irregular" for o in m["observations"])


def test_movement_artifact_excluded(synth):
    x = synth(regular(72))
    fs = 300
    i = int(14 * fs)
    x[i:i + fs] += -3 * np.hanning(fs)  # big slow swing like an arm movement
    m = analyze(x, fs)
    assert any(a <= 14.5 <= b for a, b in m["artifacts"])
    assert abs(m["hr_mean"] - 72) < 1.5


def test_slow_and_fast(synth):
    assert any("Slow" in o["title"] for o in analyze(synth(regular(44)), 300)["observations"])
    assert any("Fast" in o["title"] for o in analyze(synth(regular(115)), 300)["observations"])


def test_flat_signal_is_poor_quality():
    m = analyze(np.zeros(9000), 300)
    assert m["quality"] == "poor"


def test_determination_explanations():
    assert explain_determination("Normal Sinus Rhythm")["level"] == "info"
    assert explain_determination("Possible Atrial Fibrillation")["level"] == "flag"
    assert explain_determination("Sinus Rhythm with PVCs")["level"] == "note"
    assert explain_determination("Unclassified")["level"] == "note"
