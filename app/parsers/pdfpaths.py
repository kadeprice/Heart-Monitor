"""Pull stroked polylines out of PDF content streams.

ECG apps draw the waveform as one long run of `x y l` (lineto) operators, one
point per sample. Reading those points back gives the original signal at its
full sample rate, with no image tracing involved.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Strip string literals before tokenizing so digits inside text don't leak into operands.
_HEX_STR = re.compile(rb"<[0-9A-Fa-f\s]*>")
_LIT_STR = re.compile(rb"\((?:\\.|[^\\)])*\)")
_TOKEN = re.compile(rb"-?\d*\.?\d+(?:[eE]-?\d+)?|[A-Za-z*'\"]+|/[^\s/\[\]<>()]+")
_NUM = re.compile(rb"-?\d*\.?\d+(?:[eE]-?\d+)?$")


@dataclass
class Polyline:
    color: tuple[float, ...] | None
    points: list[tuple[float, float]] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.points)


def polylines(stream: bytes) -> list[Polyline]:
    """Return polylines in drawing order, tagged with their stroke colour.

    Consecutive `m`/`l` pairs that continue from the previous point (Kardia
    draws every segment as its own `m ... l`) are merged into one polyline.
    """
    data = _LIT_STR.sub(b" ", _HEX_STR.sub(b" ", stream))
    color: tuple[float, ...] | None = None
    nums: list[float] = []
    out: list[Polyline] = []
    cur: Polyline | None = None
    for tok in _TOKEN.findall(data):
        if _NUM.match(tok):
            nums.append(float(tok))
            continue
        op = tok
        if op == b"RG" and len(nums) >= 3:
            color = tuple(round(v, 4) for v in nums[-3:])
        elif op == b"G" and nums:
            color = (round(nums[-1], 4),) * 3
        elif op == b"m" and len(nums) >= 2:
            p = (nums[-2], nums[-1])
            if cur is None or cur.color != color or not cur.points or _dist(cur.points[-1], p) > 1e-3:
                cur = Polyline(color, [p])
                out.append(cur)
        elif op == b"l" and len(nums) >= 2 and cur is not None:
            cur.points.append((nums[-2], nums[-1]))
        nums = []
    return out


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])
