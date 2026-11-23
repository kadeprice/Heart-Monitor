# Heart Monitor

A small self-hosted web app that turns the ECG PDFs exported from a **Kardia** device and a **Pixel Watch / Fitbit**
into one history you can browse on your desktop, with a symptom log and a printable summary for your doctor.

> For personal tracking only. Not a medical device and not a diagnosis.

## What it does

- **Reads the real signal out of the PDFs.** Both apps draw the ECG as vector paths with one point per sample, so the
  app recovers the original waveform at full resolution (Kardia 300 Hz, all 6 leads on a KardiaMobile 6L; Pixel
  Watch 250 Hz, Lead I), plus the date, device result and reported heart rate.
- **Analyses every recording**: beat detection, average/min/max heart rate, early beats (PAC/PVC-style), pauses,
  beat-to-beat variability (RMSSD, SDNN, pNN50), and movement noise, which is shown and excluded from the numbers.
- **Explains results in plain language**: what the device's classification means and what this app noticed.
- **Symptom log**: one click to record palpitations with time, strength and what you were doing. Entries are matched to
  any ECG taken within an hour.
- **Doctor report**: a printable summary of results, symptoms with their matching ECGs, and recordings worth a look.
- **Automatic import (optional)**: watches a folder (e.g. a Google Drive folder synced to your server) and imports new
  PDFs on its own.

## Run it

```bash
git clone https://github.com/kadeprice/Heart-Monitor.git
cd Heart-Monitor
mkdir -p data inbox
docker compose up -d --build
```

Open `http://<your-server>:8085`. Edit `docker-compose.yml` to change the port, time zone, or import folder.

Your data lives in `./data` (SQLite database + copies of imported PDFs). Back that folder up.

**This is health data.** Keep it on your home network / VPN, or put it behind your reverse proxy with authentication.
The app itself has no login.

## Getting your PDFs

| Device | How to export |
| --- | --- |
| Kardia | Kardia app → History → open a recording → Share / PDF |
| Pixel Watch / Fitbit | Fitbit app → ECG → open a reading → Export PDF for your doctor |

Drag the PDFs onto the **Import** page (many at once is fine), or save them into the folder mounted at `/import`.
Re-importing the same file is detected and skipped.

## Development

```bash
pip install -r requirements-dev.txt
DATA_DIR=./data uvicorn app.main:app --reload
pytest
```

Put your own exports in `tests/samples/` (`kardia*.pdf`, `pixel*.pdf`) to run the parser and end-to-end tests against
real files. That folder is git-ignored so personal health data never gets committed.

When the analysis code changes, bump `ANALYSIS_VERSION` in `app/analysis.py`; existing recordings are re-analysed on
the next start.

### Layout

```
app/
  parsers/        PDF → Recording (kardia.py, pixel.py, pdfpaths.py extracts vector polylines)
  analysis.py     beat detection, metrics, plain-language observations
  service.py      import, re-analysis, symptom matching, summary
  main.py         FastAPI routes + folder watcher
  static/         single-page UI (no build step)
tests/
```
