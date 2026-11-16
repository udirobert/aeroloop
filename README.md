# AeroLoop — the independent auditor for air-quality data

Cheap air-quality data is everywhere; trusted air-quality data is not. Sensors
drift, vendors calibrate their own hardware, and the people who need the data
most can't verify it. **AeroLoop is the referee**: it scores sensors and model
fields against reference monitors, proves every correction on held-out data it
never tuned on, and keeps a verifiable audit trail — rejected ideas included.

It is location-agnostic: any sensor source, any reference network, the same
trust engine. Live today: London (LAQN) and the Netherlands (RIVM Luchtmeetnet
× sensor.community), with 22 sensor-vs-reference pairs scored.

## Quick start

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
uvicorn main:app --reload --port 8000
```

Open `http://localhost:8000` — the Pristine Air dashboard (daylight twin of the
night Ghost scene at `/scene`): verdict-first sensor↔reference audit cards with
held-out proof, a pulsing coverage map, per-sensor passports (`#/sensor/{uid}`),
printable certificates (`?certificate={uid}`), embed badges (`?embed={uid}`),
the correction tournament with rejected-idea ghosts, and the anchor proof trail.
A ①②③ guided tour pill walks first-timers from pair → proof → tournament.
`POST /demo-day` simulates a day of predictions fully offline; `POST
/tournament` runs the multi-proposer correction tournament.

## What it does

- **Audits sensors against references.** Co-located low-cost sensors are
  scored against official reference monitors on 24-hour means (indicative EPA
  comparison, not certification), with a drift heuristic on top.
- **Runs a correction tournament.** Proposers — small open-weight models,
  hosted models, a deterministic heuristic, a tabular benchmark — get the same
  prompt and tune data and must beat the incumbent on a chronological holdout;
  qualifying proposals get a blind peer soundness review.
- **Proves its history.** Every prediction is SHA-256 committed at save;
  daily Merkle roots anchor to OpenTimestamps and Base. Anyone can verify.

## Docs

| Doc | What's in it |
|---|---|
| [`docs/vision.md`](docs/vision.md) | North star: market, evidence, roadmap |
| [`docs/architecture.md`](docs/architecture.md) | Modules, data flow, endpoints, integrity rules |
| [`docs/verification.md`](docs/verification.md) | Commitment/Merkle/anchor scheme — how to verify a prediction |
| [`docs/mozilla-incubator-plan.md`](docs/mozilla-incubator-plan.md) | Mozilla Human-Scale AI application plan |
| [`docs/history.md`](docs/history.md) | Hackathon provenance: Ghost/TrueForge arcs |
| [`docs/research/positioning-2026-11.md`](docs/research/positioning-2026-11.md) | Evidence base (42 sources) |
| [`AGENTS.md`](AGENTS.md) | Agent guide: commands, integrity rules, env vars |

Submissions: [`SUBMISSION-OPENSERV.md`](SUBMISSION-OPENSERV.md) ·
[`SUBMISSION.md`](SUBMISSION.md) · [demo video](https://youtu.be/LqHMPDhwT1o)

## Status

- First real sensor-vs-reference audits done (NL, 1–9 Nov 2026): PM2.5
  4 fit / 3 drifting / 4 unfit; PM10 11/11 unfit — evidence in
  `submission/evidence/`.
- 22,309-pair model hindcast audited and anchored on Base Sepolia.
- Next: Breathe London sensors (key pending), public deployment, open
  tournament. Roadmap in [`docs/vision.md`](docs/vision.md#roadmap).
