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
- **frontend/index.html** — Pristine Air dashboard: verdict-first single column,
  guided ①②③ tour, pulsing audit map (unaudited dimmed), pair cards → scatter
  proof, sensor passports (`#/sensor/{uid}`), certificates (`?certificate=`),
  embed badges (`?embed=`), tournament lanes + ghost graveyard. Light/dark via
  `?theme=` + toggle. No backend changes; all integrity rules hold.
- **frontend/scene.html + scene.js** — "The Ghost Over London": spectral 3D
  scene (vendored three.js, no build step, no CDN). Real OSM buildings/roads
  as wireframe traces, modelled PM2.5 as wind-advected haze, station beacons,
  error wisps, scripted film mode with captions + real-verdict stamp.
- **tools/bake_city.py** — one-off Overpass bake → `frontend/london-city.json`
  (26k buildings, 10k roads, ~7MB; heights from OSM tags or seeded estimate).
- **prediction.py** — `v1-baseline` (model + humidity correction) and `v2-improved`
  (model + humidity/wind/precip + bias). Params are versioned and agent-editable.
- **evaluation.py** — MAE, RMSE, bias over matched prediction/reading pairs; breakdown by station.
- **agent.py** — self-improvement loop (`/self-improve`) and the correction
  **tournament** (`/tournament`): multiple proposers (SERV Nano, SERV Ultra,
  hosted open-weight models, deterministic heuristic; TabPFN benchmark-only)
  get identical prompt and tune data, are scored on the same hidden holdout
  across rolling windows, with cost/latency/tokens recorded per proposal.
  Accuracy gate = holdout; soundness gate = Reppo peer evaluation.
- **reppo.py** — blind peer-evaluation gate: proposals that pass accuracy are
  scored for physical plausibility (catches quoting test values, overfit).
- **proposers.json** — proposer registry (endpoints, models, SERV on/off).
- **commitments.py** — SHA-256 commit-before-truth hash per prediction at save
  time; `commit_kind` ∈ live / simulated / hindcast (hindcast never claims
  pre-truth). `anchor_daily.py` builds daily Merkle batches → OpenTimestamps
  + Base (`base_anchor.py`); `/anchors/*` endpoints serve proofs.
- **reference_sites.py** — empirical reference-site qualification. Probes every
  open site × species against the data endpoint (never metadata — it's wrong
  both ways); ≥75% hourly coverage over the window qualifies. Networks:
  `laqn` (default) and `luchtmeetnet` (RIVM, NL; `--network` CLI flag).
- **trust.py** — subject-agnostic trust engine: daily-mean regression vs
  reference, US EPA 24-hr sensor targets (indicative, not certification) +
  AeroLoop drift heuristic → fit / drifting / unfit / insufficient_evidence.
  Subjects: `cams_raw`, `incumbent`.
- **sensors/** — low-cost sensor adapters (listings + readings):
  `breathe_london.py` (400+ Clarity nodes, key-gated, OGL v3 attribution is
  mandatory on anything returning its data; `ScaledValue` = operator-corrected),
  `sensor_community.py` (open, no key; area or whole-country listing),
  `luchtmeetnet.py` (RIVM reference API — used by reference_sites, not a
  low-cost source).
- **colocation.py** — tiers each listed sensor: verified_candidate (≤500 m of a
  qualifying reference), no_reference_nearby, excluded_indoor.
- **sensor_audit.py** — end-to-end sensor-vs-reference audit: pulls
  archive.sensor.community history for each verified_candidate (sub-hourly CSVs
  → UTC hourly means; P1→PM10, P2→PM25), aligns with reference network hours,
  feeds triples to trust.score_triples, persists readings, writes evidence JSON.
- **backfill_audits.py** — resumable audit backfill: re-runs
  `sensor_audit.audit` over non-overlapping historical windows, skipping
  windows already in `sensor_audits` (idempotent; `--force` re-audits).
  Grows the TimeNet corpus — one audit window = one TimeNet record.
- **db.py** — SQLite: predictions (+commitment columns), ground_readings,
  errors, strategies (incl. `-rejected`), tournament_runs/proposals, anchors,
  reference_sites, sensors, sensor_readings, sensor_audits.
- **main.py** — FastAPI: /predict, /ground-truth (LAQN-first), /evaluate,
  /self-improve, /tournament (+/tournament/runs), /demo-day, /strategies,
  /errors, /trust, /reference-sites, /colocation, /sensor-trust, /sensors,
  /overview, /config (basemap tile URL), /map-data (slim aggregate for the
  coverage map), /anchors (+build, upgrade-ots), /commitments/prediction/{id},
  /commitments/recent, /wind-field, /aq-field, /fields-timeline, /scene-state,
  dashboard (/), scene (/scene), /health.
- **connectors/** (repo root) — TimeNet dataset connector
  (`aeroloop/pm-sensor-audit`): exports each audit window as a TimeF record
  (paired low-cost + reference hourly signals, verdict annotations) with
  classification, answer and forecasting tasks for TSLM fine-tuning
  (OpenTSLM hackathon). See `connectors/README.md`.

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
Stranger Builds TrueForge challenge — documented in `history.md`:

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
