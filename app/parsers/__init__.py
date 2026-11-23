"""Turn exported ECG report PDFs into structured recordings."""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pypdf


class ParseError(ValueError):
    pass


@dataclass
class Recording:
    source: str                     # "kardia" | "pixel"
    device: str                     # e.g. "KardiaMobile 6L", "Google Pixel Watch 2"
    recorded_at: datetime           # local time as printed on the report
    determination: str              # the vendor's rhythm classification
    reported_hr: int | None
    sample_rate: float
    leads: dict[str, np.ndarray] = field(default_factory=dict)  # millivolts

    @property
    def duration_s(self) -> float:
        first = next(iter(self.leads.values()))
        return len(first) / self.sample_rate


def parse_pdf(data: bytes) -> Recording:
    from . import kardia, pixel

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as e:  # noqa: BLE001 - any pypdf failure means "not a readable PDF"
        raise ParseError(f"Could not read PDF: {e}") from e

    for mod in (kardia, pixel):
        if mod.matches(text):
            return mod.parse(reader, text)
    raise ParseError("This doesn't look like a Kardia or Pixel Watch / Fitbit ECG report.")
