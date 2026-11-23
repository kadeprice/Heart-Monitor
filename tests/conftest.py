import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
SAMPLES = Path(__file__).parent / "samples"


def synth_ecg(beat_times, fs=300, duration=30.0, noise=0.02, seed=0):
    """Crude but realistic-enough ECG: narrow R spike, small S dip and a broad T wave per beat."""
    t = np.arange(int(duration * fs)) / fs
    x = np.zeros_like(t)
    for bt in beat_times:
        x += 1.1 * np.exp(-((t - bt) / 0.012) ** 2)
        x -= 0.25 * np.exp(-((t - bt - 0.03) / 0.012) ** 2)
        x += 0.25 * np.exp(-((t - bt - 0.28) / 0.05) ** 2)
    x += np.random.default_rng(seed).normal(0, noise, len(t))
    return x


@pytest.fixture
def synth():
    return synth_ecg


def sample(prefix):
    files = sorted(SAMPLES.glob(f"{prefix}*.pdf"))
    if not files:
        pytest.skip(f"no {prefix}*.pdf in tests/samples")
    return files[0]
