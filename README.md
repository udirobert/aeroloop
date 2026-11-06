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

- **Open-weight model at the core:** the audit/analysis runs on an
  OpenAI-compatible endpoint chain — hosted **Gemma** (`google/gemma-3-27b-it`
  via Hugging Face's router; OpenRouter Gemma as fallback), then local Ollama
  (`nemotron-mini`) for a fully offline, zero-cost loop. One env var switches;
  every report records which model ran.
- **Honest degradation:** if every model endpoint fails or returns unusable
  output, a deterministic heuristic proposes params instead — and the report
  says exactly which path ran (`model_used`, `params_source`).
- **TabPFN challenger:** with a Prior Labs token, a tabular foundation model
  trains on the tune split and faces the same holdout gate as the formula.
- **Local-first:** prediction data, ground readings and strategy files stay on
  your machine. No vendor lock-in; the agent's "memory" is plain SQLite on disk.
- **Open-source harness:** FastAPI + stdlib + sqlite3. Swap the model, swap the
  data source, swap the strategy — nothing is locked in.

## Quick start

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
uvicorn main:app --reload --port 8000
```

Then open `http://localhost:8000` (serves the dashboard), `http://localhost:8000/scene`
(**The Ghost Over London** — a spectral 3D render of inner London built from real
OSM geometry, with modelled PM2.5 as wind-advected haze and the agent's errors
rising off the monitors as wisps; press "play the film" — a captured run lives
at `docs/ghost-film.mp4` / `.gif`), or `http://localhost:8000/docs`.

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
├── index.html       Dashboard: predicted-vs-measured chart, agent report, strategy memory
├── scene.html/.js   "The Ghost Over London" — spectral 3D city (vendored three.js)
├── london-city.json Baked OSM geometry (26k buildings, 10k roads) — see tools/bake_city.py
└── vendor/          three.js + postprocessing, vendored — no CDN, works offline
```

## Scientific integrity

- TROPOMI NO2 / AOD are **not** direct surface measurements — flagged as such.
- Ground-monitor readings are local, not neighbourhood-representative.
- Interpolated/estimated values are never presented as measurements.
- The holdout split is never touched by tuning — the agent only learns on the
  tune split; the holdout alone decides keep/reject.
- Ground truth resolves real LAQN (LondonAir) hourly PM2.5 where a site
  measures it — currently north_kensington (KC1), once ratified (~5-day lag).
  Where it doesn't, readings fall back to a deterministic synthetic stand-in,
  clearly labelled `synthetic` in the DB and in the API response's `source`.
- If the agent does not improve, it reports that honestly.

## Status

Core prediction + feedback + self-improvement loop works end-to-end, verified
2026-10-31. Real LAQN ground truth wired for north_kensington (KC1) 2026-11-05;
wider AURN coverage, Sentinel-5P/AOD satellite features are next priorities.

## Run 1 vs run N

*Stranger Builds · TrueForge challenge — the same agent, rebuilt on TrueForge:
a PM2.5-forecasting agent whose estimation strategy lives in
`agent/skills/pm25-strategy/SKILL.md`, which it rewrites itself.*

* **Task and score:** estimate ground-level PM2.5 for 8 fixed London
  station/hour scenarios (`evals/tasks/`); score = 100 × mean(1 − |predicted −
  measured| / 8) per task (`runs/summary.csv`).
* **Run 1 → run 4:** 63.91 → 86.09 — peak 87.03 at run 2; all 8 tasks pass by
  run 4 (`runs/summary.csv`). Then, on a clean-room replay on the sponsor
  gateway, **run 6 → run 7:** 63.91 → 80.63.
* **The change that did it:** commit `8b8c1d1` — after run 1 the agent added a
  flat +3.0 µg/m³ correction to its strategy (`Agent-Session:
  01m6ptf9n9rmc2cn38kbbns1kb`).
* **What the agent learned:** the CAMS model systematically under-reads the
  ground monitors; after overshooting once (+3.0 → +2.0, an honest regression
  to 83.28) it learned a station-specific correction — +2.0 everywhere, +4.6
  at Marylebone. On the second arc a different model reached the same
  conclusion a different way: a ×1.20 uplift (`Agent-Session:
  01m6pw7n97x4g1k9mavc9k3frh`) — same lesson, different hypothesis.
* **What still fails:** nothing material on the task set — the residual error
  is irreducible monitor noise (~±3 µg/m³). Run 5 (55.94) carries one
  transient transport error, kept in the record rather than silently rerun.

Two independent learning arcs are in the record: runs 1–4 on
`huggingface/gemma-3-27b-it`, runs 5–8 on `truefoundry/kimi-k27-code`
(open weights served through the organisers' managed AI Gateway, on the
provided credits). Runs 9–10 switch `skill_mode` to `"git"`: the agent reads
its skill as a **real TrueForge skill** cloned from this repo at the pinned
commit through the local sandbox — the starter's `TODO(verify)` path,
verified end-to-end (see `runs/run-09/session.json`: `sandbox.created` and
skill-read tool calls).

**Generalization check — `evals/hard/` (runs 11–13):** the learned playbook
was then frozen against a 24-task suite it never saw (6/station, 4 holdout).
Its ×1.20 rule scored **55.1 → improved to 63.65** after one self-edit that
replaced the single multiplier with per-station uplifts plus an NO2 traffic
term — the honest finding being that the small-suite correction *didn't*
generalize, and the agent diagnosed that itself. Run 13 (61.77, one unparsed
reply) and a rejected self-edit (the overfit guard caught it quoting a task
value) are kept in the record too.

### Run it

```bash
npm install
npx @truefoundry/trueforge@latest   # keep running; serves http://localhost:8790
npm run configure-model             # registers providers from backend/.env keys
npm run setup && npm run run-evals  # baseline
npm run improve && npm run run-evals
```

The backend is untouched — this harness (`agent/`, `evals/`, `scripts/`,
`runs/`) sits alongside it and treats AeroLoop's recorded prediction/reading
pairs as the eval set. Ground truth remains the labelled synthetic stand-in;
the scorer is a deterministic port of `evaluation.py`'s error logic.
