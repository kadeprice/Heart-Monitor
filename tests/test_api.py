import importlib

import pytest
from fastapi.testclient import TestClient

from conftest import SAMPLES


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("IMPORT_DIR", raising=False)
    from app import db, main, service
    importlib.reload(db)
    importlib.reload(service)
    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c


def test_symptom_roundtrip(client):
    r = client.post("/api/symptoms", json={"occurred_at": "2026-05-18T10:40", "kind": "Palpitations", "severity": 4})
    assert r.status_code == 200
    rows = client.get("/api/symptoms").json()
    assert rows[0]["kind"] == "Palpitations" and rows[0]["recordings"] == []
    assert client.delete(f"/api/symptoms/{rows[0]['id']}").json() == {"ok": True}


def test_import_rejects_non_pdf(client):
    r = client.post("/api/import", files=[("files", ("x.txt", b"hello", "text/plain"))])
    assert r.json()["results"][0]["status"] == "error"


def test_static_index(client):
    r = client.get("/")
    assert r.status_code == 200 and "Heart Monitor" in r.text


def test_import_samples_end_to_end(client):
    pdfs = sorted(SAMPLES.glob("*.pdf"))
    if not pdfs:
        pytest.skip("no sample PDFs")
    files = [("files", (p.name, p.read_bytes(), "application/pdf")) for p in pdfs]
    res = client.post("/api/import", files=files).json()["results"]
    assert all(r["status"] == "imported" for r in res), res
    again = client.post("/api/import", files=files[:1]).json()["results"]
    assert again[0]["status"] == "duplicate"
    rec = client.get(f"/api/recordings/{res[0]['id']}").json()
    assert rec["metrics"]["hr_mean"] > 30
    sig = client.get(f"/api/recordings/{res[0]['id']}/signal").json()
    assert sig["fs"] in (250, 300) and sig["beats"]
    assert client.get(f"/api/recordings/{res[0]['id']}/pdf").status_code == 200
    s = client.get("/api/summary").json()
    assert s["recording_count"] == len(pdfs)
