# AeroLoop — the independent auditor for air-quality data

> AeroLoop corrects any sensor or model against reference monitors, proves every
> correction on held-out data it never tuned on, has each change peer-verified,
> and keeps an audit trail of what changed and why — rejected ideas included.

**Vision, market and roadmap:** [`docs/vision.md`](docs/vision.md) ·
**Evidence (42 sources):** [`docs/research/positioning-2026-11.md`](docs/research/positioning-2026-11.md) ·
**OpenServ Hackathon 2 submission:** [`SUBMISSION-OPENSERV.md`](SUBMISSION-OPENSERV.md) ·
[demo video](docs/aeroloop-openserv-demo.mp4)

## Why it matters

Cheap air-quality data is everywhere; trusted air-quality data is not. Low-cost
sensors drift, vendors calibrate their own hardware, and the UK's Institute of
Air Quality Management has warned that many low-cost sensors under-report PM10
near the 190 µg/m³ construction action level. From **12 December 2026** the
revised EU Ambient Air Quality Directive sets numeric uncertainty limits for
every type of evidence. What's missing is an independent party that produces
**proof** a correction is valid. That is AeroLoop.

First market: UK construction and demolition dust monitoring, where Section 61
consents and planning conditions already require continuous PM10 monitoring and
the developer pays. See [`docs/vision.md`](docs/vision.md) for who pays, why
now, and what we deliberately are not.

## How it works

Today the subject under audit is CAMS model PM2.5 at four London stations (real
LAQN reference truth at North Kensington; a labelled synthetic stand-in
elsewhere). The loop:

1. Predicts PM2.5 at a London monitoring station using only data available at prediction time.
2. Saves the prediction **before** seeing the ground truth.
3. Retrieves the actual ground-monitor reading once available.
4. Computes the error (MAE, RMSE, bias).
5. Analyses recurring errors **on a tune split** and proposes a strategy change
   (prose + parameters). In tournament mode (`POST /tournament`) several
   proposers — SERV Nano, SERV Ultra, an open-weight model, a deterministic
   heuristic, and TabPFN as a benchmark-only challenger — get byte-identical
   prompts built from tune data only.
6. Re-evaluates every proposal on a **chronological holdout** the tuning step
   never saw, split into time windows: a proposal must beat the incumbent
   overall *and* in a majority of windows.
7. Sends qualifying proposals to a blind Reppo peer review for soundness, keeps
   the best one that passes — and remembers rejections too.

Every prediction is also hashed when it is saved, and daily batches are
anchored on OpenTimestamps and Base so anyone can check it existed by a given
time (see [Verify a prediction](#verify-a-prediction)).

## Where it came from

AeroLoop started as a Hacktoberfest 2026 "Ghost in the Machine" entry (rejected
strategies are kept as `vN-rejected` — the ghosts of ideas that didn't work;
see [`SUBMISSION.md`](SUBMISSION.md) and the "Ghost Over London" scene), then
became a Stranger Builds / TrueForge entry (see "Run 1 vs run N" below). Those
entries are kept as history; the direction now is [`docs/vision.md`](docs/vision.md).

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

**Reference data tooling (Milestone 2):**

```bash
DATABASE_PATH=../data/x.db python reference_sites.py --start YYYY-MM-DD --end YYYY-MM-DD  # probe every LAQN site, keep ≥75% coverage
DATABASE_PATH=../data/x.db python backfill_laqn.py --all-qualifying --start .. --end ..   # multi-site hindcast (laqn:CODE stations)
DATABASE_PATH=../data/x.db python colocation.py --refresh                                # sensor listings + co-location tiers
DATABASE_PATH=../data/x.db python score_real_audit.py --out out.json                     # per-site + overall holdout scores
```

Endpoints: `GET /reference-sites`, `GET /trust?subject=cams_raw|incumbent`,
`GET /colocation?species=PM25`. Trust scores apply the US EPA 2021 PM2.5
24-hour performance targets as an **indicative comparison, not certification**.

## Architecture

```
backend/
├── main.py          FastAPI app + routes + dashboard serving
├── models.py        Pydantic schemas (Prediction, GroundReading, Error, Strategy)
├── db.py            SQLite persistence (predictions, readings, errors, strategies)
├── data_sources.py  Open-Meteo Air Quality + weather fetchers (London)
├── prediction.py    v1 baseline + v2 parametric correction strategies
├── evaluation.py    MAE / RMSE / bias over matched prediction/reading pairs
├── agent.py         Self-improvement loop + correction tournament (holdout windows, winner rule)
├── proposers.json   Tournament proposer registry (no secrets; keys come from env)
├── reppo.py         Reppo Evaluation API client — blind soundness gate
├── commitments.py   Prediction hashes, Merkle batches, OpenTimestamps, verify view
├── base_anchor.py   Anchors daily Merkle roots on Base (Sepolia by default)
├── anchor_daily.py  Cron entry point: build yesterday's batch, stamp OTS, anchor on Base
├── backfill_laqn.py Real-reference hindcast against ratified LAQN data (kind "hindcast")
├── score_real_audit.py  Scores strategies on the LAQN hindcast
└── tests/           pytest suite (no network)
anchors/             Published daily batch records (<date>.json, .root, .root.ots)
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

## Verify a prediction

Every prediction is **committed when it is saved**. At save time the
backend builds a canonical JSON payload (sorted keys, no spaces) containing the
station, timestamp, predicted value, strategy, inputs and a `committed_at`
UTC stamp, and stores its SHA-256 as `commit_hash` plus the exact payload
string. `GET /commitments/prediction/{id}` re-hashes the stored payload and
reports `hash_matches`, the reading that arrived later, and
`reading_recorded_after_commit` (reading `recorded_at` > `committed_at`).

`committed_at` is **self-reported** by the AeroLoop server — by itself it
proves nothing. What is publicly provable is *"this exact prediction existed
by `<anchor time>`"*: once the day's Merkle root is confirmed on Base, the
block timestamp (`existed_by`) is a third-party bound, and once the
OpenTimestamps receipt upgrades, the Bitcoin block is another. A verifier
then compares that bound with when the truth became public — LAQN ratified
readings are published days later, so **daily anchoring is sufficient for
ratified-truth audits, but cannot prove a same-day forecast**.
`target_after_existed_by` reports whether the prediction's target timestamp
postdates the anchor bound (i.e. it provably predated the hour it predicts).

Each `kind` says what the commitment means:

- `live` — predicted in real time, truth not yet published: the real claim.
- `simulated` — `/demo-day` offline pairs; labelled, never presented as live.
- `hindcast` — backfilled over already-ratified truth; the commitment records
  *when* the row was written, not a pre-truth guarantee.
- `uncommitted` — legacy rows predating commitments (hash fields NULL).

Daily, all un-anchored commits are folded into a Merkle tree —
`aeroloop-merkle-v1`: `leaf = sha256(0x00‖hash)`, `node = sha256(0x01‖left‖right)`,
last node duplicated on odd levels, leaves ordered by prediction id. The batch
record lands in `anchors/<date>.json` — the **published record**. The verify
endpoint rebuilds the proof from that file (not from mutable DB rows),
recomputes its root, and reports `published_root` plus `roots_consistent`
(published root == DB anchor root).

The root is anchored twice:

- **Bitcoin (OpenTimestamps).** `anchors/<date>.root` holds the 32 raw root
  bytes and is stamped with `ots stamp`; verify with
  `ots verify anchors/<date>.root.ots`. OTS commits to `sha256` of that file,
  i.e. to `sha256(root_bytes)`.
- **Base.** A self-send transaction carries calldata `"AEROLOOP1" + root` —
  check it on the explorer (`basescan.org` / `sepolia.basescan.org`) linked
  from `GET /anchors`. Base Sepolia by default; see `.env.example`.

## Roadmap

AeroLoop is becoming **Proof of Air**: a neutral referee that scores any
proposer's corrections on hidden future data (a tournament that doubles as a
public SERV benchmark), gates each change on a Reppo peer verdict, hashes every
prediction before its truth exists, rates London's low-cost sensors on a live
trust map, and sells verification over OpenServ's x402 marketplace. Milestones
in [`docs/vision.md`](docs/vision.md#roadmap).

## Status

- Core predict → truth → score → improve loop: working since 2026-10-31.
- Real LAQN reference truth for North Kensington (KC1); 192-hour ratified
  hindcast audit in `submission/evidence/real-audit-scores.json`.
- Correction tournament with SERV proposers and the blind Reppo gate: built,
  tested, and the Reppo gate verified against the live API (verdict in ~90 s,
  440 credits per evaluation).
- Prediction hashes, Merkle batches and OpenTimestamps stamping: working; Base
  anchoring built and tested against a mocked node, not yet sent on-chain.
- Milestone 2a: 26 reference sites qualified by probing data, a 40-day
  multi-site hindcast (22,309 pairs), and a trust engine scoring against US EPA
  24-hour targets (indicative). First finding: raw CAMS is unfit at all 26
  sites — it under-responds by roughly half — and the current offset-only
  correction can't fix that (`submission/evidence/real-audit-multisite.json`).
- The strategy can now scale CAMS as well as shift it. A tournament on the
  26-site data improved holdout MAE ~4% but every site stays unfit; both SERV
  proposers were refused by SERV's content filter
  (`submission/evidence/tournament-multisite-scale-run1.json`).
- Next: reference-data quality filter, episode-aware corrections, Breathe
  London sensors (needs a key), sensor trust tiers and the trust map.

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
