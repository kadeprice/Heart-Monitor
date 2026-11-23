import numpy as np

from app.parsers import ParseError, parse_pdf
from app.parsers.pdfpaths import polylines
from conftest import sample


def test_polylines_merges_segments_and_ignores_text():
    stream = (b"0 0 0 RG BT (12 34 l) Tj ET <0031> Tj\n"
              b"1 2 m 2 3 l S 2 3 m 3 1 l S 9 9 m 10 9 l S\n"
              b".5 .5 .5 RG 0 0 m 100 0 l S")
    lines = polylines(stream)
    assert [len(p) for p in lines] == [3, 2, 2]
    assert lines[0].points == [(1, 2), (2, 3), (3, 1)]
    assert lines[2].color == (0.5, 0.5, 0.5)


def test_rejects_non_ecg_pdf():
    import pytest
    with pytest.raises(ParseError):
        parse_pdf(b"%PDF-1.4 not really a pdf")


def test_kardia_sample():
    r = parse_pdf(sample("kardia").read_bytes())
    assert r.source == "kardia"
    assert r.sample_rate == 300
    assert r.determination
    assert set(r.leads) in ({"I"}, {"I", "II", "III", "aVR", "aVL", "aVF"})
    n = {len(v) for v in r.leads.values()}
    assert len(n) == 1 and abs(r.duration_s - 30) < 1
    assert 0.3 < np.percentile(r.leads["I"], 99.9) < 5  # R waves in a plausible mV range


def test_pixel_sample():
    r = parse_pdf(sample("pixel").read_bytes())
    assert r.source == "pixel"
    assert r.sample_rate == 250
    assert list(r.leads) == ["I"]
    assert 25 < r.duration_s < 31
    assert 0.3 < np.percentile(r.leads["I"], 99.9) < 5
