# AeroLoop — agent guide

## Direction (read first)

AeroLoop is **the independent auditor for air-quality data**: it corrects any
sensor or model against reference monitors, proves every correction on held-out
data it never tuned on, has each change peer-verified (Reppo), and keeps an audit
trail including rejected ideas. North star: [`docs/vision.md`](docs/vision.md).
Evidence: [`docs/research/positioning-2026-11.md`](docs/research/positioning-2026-11.md).

When changing product, demo or docs, check the change against the vision:
- First market is UK construction/demolition dust monitoring (PM10, 190 µg/m³
  action level); second is EU operators under Directive 2024/2881. Councils are
  users first, not first buyers.
- Not a sensor company, not a forecast API, not a certification body.
- The Hacktoberfest "ghost" framing and the Stranger Builds/TrueForge harness are
  history; keep them working, but don't lead with them.

## Integrity rules (non-negotiable)

- Never present modelled (CAMS/Open-Meteo) or synthetic values as measurements.
  Synthetic readings stay labelled `synthetic` in the DB and API `source`.
- The holdout split is never used for tuning.
- Rejected strategies are recorded, never deleted.
- Prediction commitments: `committed_at` is self-reported; only the anchor time
  is publicly proven. Never describe `hindcast` or `simulated` rows as pre-truth.
- Comparisons to EU directive uncertainty limits are labelled *indicative* unless
  computed by the formal method; we do not issue MCERTS/CEN classifications.
- Reference sites qualify by probing their data (≥75% of hours), never by LAQN
  metadata, which is wrong in both directions.
- Anything that returns or displays Breathe London data must carry: "Contains
  Breathe London data licensed under the Open Government License v3.0" linking
  https://www.breathelondon.org/ (OGL v3).
- Trust statuses compare against US EPA 24-hour targets and are indicative, not
  certification; the drift flag is an AeroLoop heuristic.
- Market numbers in docs must trace to a source in the research report; label
  hypotheses (e.g. pricing) as hypotheses.

## Commands

```bash
# backend (FastAPI)
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && cp ../.env.example .env
uvicorn main:app --reload --port 8000   # dashboard at http://localhost:8000

# lint (config in .ruff.toml) and tests (no network; uses temp DBs)
ruff check backend
cd backend && pip install -r requirements-dev.txt && python -m pytest -q
# On this Mac the shell can flip to Rosetta; if a wheel fails to import, run
# `arch -arm64 .venv/bin/python -m pytest -q`.

# TrueForge harness (Node >= 22.14)
npm install && npm run typecheck
```

Demo loop: `POST /demo-day` (offline, 24h of predictions + delayed truth), then
`POST /tournament` (or the older single-proposer `POST /self-improve`).

Anchoring: `POST /anchors/build?date=YYYY-MM-DD` (or `python anchor_daily.py`)
builds a day's Merkle batch into `anchors/`, stamps OpenTimestamps and anchors on
Base. Tests and smoke runs must set `ANCHORS_DIR` and `DATABASE_PATH` to temp
paths so nothing lands in the real `anchors/` or `data/`.

Media: video files are gitignored. The only tracked videos are the ones the
README and submissions link to (`docs/aeroloop-openserv-demo.mp4`,
`docs/ghost-film.mp4`, `docs/ghost-film.gif`); don't add others.

`video/` is a separate HyperFrames project with its own `AGENTS.md`.
