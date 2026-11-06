# AeroLoop — Architecture

## Modules

- **data_sources.py** — Open-Meteo Air Quality (CAMS PM2.5/NO2) + weather. Ground truth:
  real LAQN (LondonAir) hourly PM2.5 where a site measures it — currently
  **north_kensington (KC1)** only — resolved when the prediction's hour is old
  enough to be ratified (~5-day publication lag, which suits the delayed-truth
  mechanic). Otherwise a deterministic synthetic stand-in keeps the demo loop
  runnable fully offline (md5-seeded, reproducible). The reading's `source`
  says which path ran. Also gridded field fetchers for the scene:
  `fetch_wind_field()` / `fetch_aq_field()` — one multi-coordinate Open-Meteo
  call each, mem-cache → `data/cache/` → labelled synthetic fallback.
- **frontend/scene.html + scene.js** — "The Ghost Over London": spectral 3D
  scene (vendored three.js, no build step, no CDN). Real OSM buildings/roads
  as wireframe traces, modelled PM2.5 as wind-advected haze, station beacons,
  error wisps, scripted film mode with captions + real-verdict stamp.
- **tools/bake_city.py** — one-off Overpass bake → `frontend/london-city.json`
  (26k buildings, 10k roads, ~7MB; heights from OSM tags or seeded estimate).
- **prediction.py** — `v1-baseline` (model + humidity correction) and `v2-improved`
  (model + humidity/wind/precip + bias). Params are versioned and agent-editable.
- **evaluation.py** — MAE, RMSE, bias over matched prediction/reading pairs; breakdown by station.
- **agent.py** — self-improvement loop:
  1. Split matched pairs chronologically: tune (earlier ~2/3) / holdout (later ~1/3).
  2. Compute incumbent-strategy errors on the **tune** split only.
  3. Ask the open-weight LLM for an analysis AND proposed params (clamped to sane
     bounds; deterministic heuristic if every endpoint fails or returns junk).
  4. Score incumbent and candidate on the **holdout** split — data the tuning step
     never saw. A TabPFN foundation-model challenger runs the same gate.
  5. Keep the candidate only if holdout MAE improves; otherwise save it anyway as
     `<v>-rejected` — rejected ideas stay in the record (the ghosts).
- **db.py** — SQLite (predictions, ground_readings, errors, strategies).
- **main.py** — FastAPI: /predict, /ground-truth (LAQN-first), /evaluate,
  /self-improve, /demo-day, /strategies, /errors, /wind-field, /aq-field,
  /scene-state, dashboard (/), scene (/scene).

## Data flow

```
Open-Meteo AQ + Weather  -->  features  -->  predict(strategy, features)  -->  save prediction
                                                                              (no ground truth yet)
ground truth arrives  -->  save reading  -->  matched pair
                                                |
                          tune split  -->  LLM analyses errors, proposes params
                                                |
                          holdout split  -->  score incumbent vs candidate
                                                -->  keep (vN) or reject (vN-rejected)
```

## Scientific constraints honoured

- CAMS/Open-Meteo output is a **model forecast**, never a measurement.
- Ground readings are **local**, not neighbourhood-representative.
- Interpolated/estimated values are never presented as measurements.
- The holdout split is never touched by the tuning/analysis step — the agent only
  "learns" on the tune split; the holdout decides keep/reject.
- If the agent does not improve, it reports that honestly (`<v>-rejected` stays
  in the strategies table).
- `model_used` and `params_source` in every report record exactly which model
  (or fallback) produced each strategy.

## Trade-offs

- SQLite over PostGIS for v1 (speed of build). Migrate to Postgres+PostGIS for spatial queries.
- Synthetic ground readings for the offline demo loop; swap in DEFRA AURN for production.
- Open-weight reasoning via an endpoint chain, tried in order and reported per
  run: hosted Gemma (`google/gemma-3-27b-it` on Hugging Face's OpenAI-compatible
  router) → second hosted Gemma (OpenRouter) → local Ollama (`nemotron-mini`,
  fully offline). `model_used`/`params_source` record which path produced each
  strategy.
- **TabPFN challenger** (Prior Labs): when `TABPFN_ACCESS_TOKEN` is set, a
  tabpfn-client regressor is trained on the tune split and scored on the same
  holdout. If it beats both candidates it is recorded as a `vN-tabpfn` strategy
  (audit-only for now — live prediction still uses the parametric incumbent).
- No torch/sklearn locally — the linear strategies are stdlib math and TabPFN
  inference is hosted, so the backend installs in seconds and runs on anything.

## TrueForge harness (Stranger Builds)

Alongside the backend, a second, self-contained self-improvement loop for the
Stranger Builds TrueForge challenge — documented in `stranger-builds.md`:

- `agent/` — the `pm25-forecaster` TrueForge agent: `agent.json`, its
  `instructions.md`, and `skills/pm25-strategy/SKILL.md`, the playbook the
  agent rewrites itself (the TrueForge analogue of `prediction.py`'s params).
- `evals/` — 8 fixed forecast tasks built from `data/aeroloop.db` matched
  pairs (features + measured ground truth; 2 holdout), plus `evals/hard/` —
  a second, unseen 24-task suite (6/station, 4 holdout) used for the
  generalization experiment (runs 11–13) — and `score.ts`, a deterministic
  port of `evaluation.py`'s error logic (score = 1 − |err|/8).
- `scripts/` — TypeScript driver around `@truefoundry/trueforge-sdk`:
  `configure-model` (registers model providers incl. the organisers' managed
  AI Gateway), `setup`, `run-evals` (one TrueForge session = one run;
  `--tasks-dir` selects the suite), `improve` (the agent rewrites `agent/`,
  committed with `Agent-Session:`), `export-session`, `score`. `runs/` holds
  every run's results, session export and `summary.csv`.
