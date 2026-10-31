# AeroLoop — A Self-Improving Air Quality Intelligence Agent

> **Hacktoberfest Week 4 (Oct 26–31, 2026) — "Ghost in the Machine" entry.**
> A self-improving agent that predicts PM2.5 over London, compares against ground
> monitors, finds patterns in its own errors, rewrites its own estimation strategy,
> and proves — on a fixed held-out benchmark — whether it actually got better.

## What it is

AeroLoop is not a dashboard. It's an autonomous agent that gets **measurably better**
at a real-world task: estimating local PM2.5 air pollution. It:

1. Predicts PM2.5 at a London monitoring station using only data available at prediction time.
2. Saves the prediction **before** seeing the ground truth.
3. Retrieves the actual ground-monitor reading once available.
4. Computes the error (MAE, RMSE, bias).
5. Analyses recurring errors and proposes a strategy change.
6. Rewrites its own estimation strategy (a versioned skill file).
7. Re-evaluates on a fixed held-out benchmark.
8. Keeps the change only if it genuinely improves performance.

## The "Ghost in the Machine" angle

Air quality is the ghost of the city's past — the invisible residue of traffic,
industry and weather that lingers long after the source is gone. AeroLoop honours
that history: it remembers every prediction, every error, every lesson, and carries
them forward in versioned, auditable strategy files. The "ghost" is the model's own
memory of mistakes, made tangible and measurable.

## Open innovation

- **Open-weight model at the core:** the audit/analysis agent runs on a local
  open-weight model (Gemma / Qwen 2.5) via an OpenAI-compatible endpoint
  (Ollama). No closed API key required for the reasoning loop.
- **Local-first:** prediction data, ground readings and strategy files stay on
  your machine. No vendor lock-in; the agent's "memory" is plain JSON on disk.
- **Open-source harness:** FastAPI + scikit-learn + pandas. Swap the model, swap
  the data source, swap the strategy — nothing is locked in.

## Quick start

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
uvicorn main:app --reload --port 8000
```

Then open `http://localhost:8000` (serves the dashboard) or `http://localhost:8000/docs`.

## Architecture

```
backend/
├── main.py          FastAPI app + routes + dashboard serving
├── models.py        Pydantic schemas (Prediction, GroundReading, Error, Strategy)
├── db.py            SQLite persistence (predictions, readings, errors, strategies)
├── data_sources.py  Open-Meteo Air Quality + weather fetchers (London)
├── prediction.py    Baseline (v1) + improved (v2) estimation strategies
├── evaluation.py    MAE / RMSE / bias on a fixed held-out benchmark
└── agent.py         Self-improvement loop: analyse errors → propose → rewrite strategy → evaluate
frontend/
└── index.html       Minimal dashboard (map placeholder + learning curve)
```

## Scientific integrity

- TROPOMI NO2 / AOD are **not** direct surface measurements — flagged as such.
- Ground-monitor readings are local, not neighbourhood-representative.
- Interpolated/estimated values are never presented as measurements.
- Test-set ground truth is never used when the agent modifies its strategy.
- If the agent does not improve, it reports that honestly.

## Status

Scaffolded on 2026-10-31 for Hacktoberfest Week 4. Core prediction + feedback
loop is the priority; satellite sources (Sentinel-5P, AOD) are Priority 4.
