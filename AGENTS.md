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
- Comparisons to EU directive uncertainty limits are labelled *indicative* unless
  computed by the formal method; we do not issue MCERTS/CEN classifications.
- Market numbers in docs must trace to a source in the research report; label
  hypotheses (e.g. pricing) as hypotheses.

## Commands

```bash
# backend (FastAPI)
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && cp ../.env.example .env
uvicorn main:app --reload --port 8000   # dashboard at http://localhost:8000

# lint (config in .ruff.toml)
ruff check backend

# TrueForge harness (Node >= 22.14)
npm install && npm run typecheck
```

Demo loop: `POST /demo-day` (offline, 24h of predictions + delayed truth), then
`POST /self-improve`.

`video/` is a separate HyperFrames project with its own `AGENTS.md`.
