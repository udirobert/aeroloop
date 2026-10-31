# AeroLoop — A Self-Improving Air Quality Intelligence Agent

> **Hacktoberfest Week 4 (Oct 26–31, 2026) — "Ghost in the Machine" entry.**
> A self-improving agent that predicts PM2.5 over London, compares against ground
> monitors, finds patterns in its own errors, rewrites its own estimation strategy,
> and proves — on data it never tuned against — whether it actually got better.

## What it is

AeroLoop is not a dashboard. It's an autonomous agent that gets **measurably better**
at a real-world task: estimating local PM2.5 air pollution. It:

1. Predicts PM2.5 at a London monitoring station using only data available at prediction time.
2. Saves the prediction **before** seeing the ground truth.
3. Retrieves the actual ground-monitor reading once available.
4. Computes the error (MAE, RMSE, bias).
5. Analyses recurring errors **on a tune split** and proposes a strategy change
   (prose + parameters, via an open-weight model).
6. Re-evaluates on a **chronological holdout** the tuning step never saw.
7. Keeps the change only if it genuinely improves — and remembers rejections too.

## The "Ghost in the Machine" angle

Air quality is the ghost of the city's past — the invisible residue of traffic,
industry and weather that lingers long after the source is gone. AeroLoop honours
that history: it remembers every prediction, every error, every lesson, and carries
them forward in versioned, auditable strategy files. Rejected strategies stay in the
record as `vN-rejected` — the ghosts of ideas that didn't work. The "ghost" is the
model's own memory of mistakes, made tangible and measurable.

## Open innovation

- **Open-weight model at the core:** the audit/analysis runs on any
  OpenAI-compatible endpoint — `nemotron-mini` via Ollama for a fully offline,
  zero-cost loop, or hosted **Gemma** (`gemma2-9b-it` via e.g. Groq) for a stronger
  reasoner. One env var switches; every report records which model ran.
- **Honest degradation:** if the model can't be reached or returns unusable
  output, a deterministic heuristic proposes params instead — and the report
  says exactly which path ran (`model_used`, `params_source`).
- **Local-first:** prediction data, ground readings and strategy files stay on
  your machine. No vendor lock-in; the agent's "memory" is plain SQLite on disk.
- **Open-source harness:** FastAPI + stdlib + sqlite3. No pandas/sklearn — the
  whole backend installs in seconds. Swap the model, swap the data source, swap
  the strategy — nothing is locked in.

## Quick start

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
uvicorn main:app --reload --port 8000
```

Then open `http://localhost:8000` (serves the dashboard) or `http://localhost:8000/docs`.

**One-click demo:** `POST /demo-day` simulates 24h of predictions + delayed ground
truth across all 4 stations, fully offline. Then `POST /self-improve` runs the
whole analyse → propose → holdout-evaluate → keep/reject loop.

## Architecture

```
backend/
├── main.py          FastAPI app + routes + dashboard serving
├── models.py        Pydantic schemas (Prediction, GroundReading, Error, Strategy)
├── db.py            SQLite persistence (predictions, readings, errors, strategies)
├── data_sources.py  Open-Meteo Air Quality + weather fetchers (London)
├── prediction.py    v1 baseline + v2 parametric correction strategies
├── evaluation.py    MAE / RMSE / bias over matched prediction/reading pairs
└── agent.py         Self-improvement loop: tune-split analysis → holdout gate → keep/reject
frontend/
└── index.html       Dashboard: predicted-vs-measured chart, agent report, strategy memory
```

## Scientific integrity

- TROPOMI NO2 / AOD are **not** direct surface measurements — flagged as such.
- Ground-monitor readings are local, not neighbourhood-representative.
- Interpolated/estimated values are never presented as measurements.
- The holdout split is never touched by tuning — the agent only learns on the
  tune split; the holdout alone decides keep/reject.
- Synthetic ground readings (demo mode) are deterministic and clearly labelled
  `synthetic` in the DB — swap in DEFRA AURN for production.
- If the agent does not improve, it reports that honestly.

## Status

Core prediction + feedback + self-improvement loop works end-to-end, verified
2026-10-31. Satellite sources (Sentinel-5P, AOD) and real DEFRA AURN ground truth
are next priorities.
