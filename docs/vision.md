# AeroLoop — Vision

> **AeroLoop is the independent auditor for air-quality data.**
> It corrects any sensor or model against reference monitors, proves every
> correction on held-out data it never tuned on, has each change peer-verified,
> and keeps an audit trail of what changed and why — rejected ideas included.

This document is the north star. Product, demo, write-ups and roadmap should all
trace back to it. The evidence behind every claim here is in
[`research/positioning-2026-11.md`](research/positioning-2026-11.md) (42 sources).

---

## The problem

Cheap air-quality data is everywhere; **trusted** air-quality data is not.

- Low-cost sensors drift. Calibration factors "change with time and space",
  and PurpleAir data shows bias drifting by ~0.12 µg/m³ per year.
- The people who calibrate a sensor are usually the people who sold it.
  Calibration is bundled free inside vendor subscriptions and described as
  proprietary — useful, but not independent.
- The professional body for UK air quality (IAQM, Sept 2025) says many low-cost
  sensors under-report PM10 near the 190 µg/m³ construction action level —
  exactly where they matter — and that certificates alone don't prove fitness.
- The European Commission says accuracy issues currently prevent low-cost
  sensors from supporting the revised Ambient Air Quality Directive.

Nobody in the chain is an independent party producing **proof**.

## Why now

| Trigger | Date | What it means |
|---|---|---|
| EU Directive 2024/2881 applies | **12 Dec 2026** | Numeric max uncertainty per evidence type (PM2.5 indicative: 4 µg/m³ / 40%); PM2.5 limit 25 → 10 µg/m³ by 2030 |
| Clean Tech for Clean Air coalition | Jul 2026 | Airly, Clarity, Kunak, Ellona, Ecomesure lobbying for authorities to accept sensor data |
| IAQM position statement | Sep 2025 | Low-cost PM10 sensors questioned near action levels; certification not enough |
| England Environment Act target | 2040 | PM2.5 annual mean ≤ 10 µg/m³; 35% exposure reduction vs 2018 |

## Who pays

**First market — UK construction & demolition dust monitoring.**
Section 61 consents and planning conditions already require continuous PM10
monitoring; the developer pays; consultancies charge **£500–1,500 per
monitoring point per month**. The IAQM statement has put sensor fitness near
the action level in question. An independent verification appendix — "this
sensor, at this site, this month, was / was not fit near 190 µg/m³, and here
is the held-out evidence" — protects the contractor, the consultant and the
planning officer.

**Second market — EU sensor operators and integrators** who need independent
evidence that their data meets indicative-measurement quality under
2024/2881. The sensor coalition is a potential partner, not a competitor:
verified data is what it is asking authorities to accept.

**Later — data and agent channels.** A corpus of corrections, each with a
held-out score, is licensable data. A pay-per-call "verify this series"
endpoint fits OpenServ's x402 marketplace. AeroLoop's predict-before-truth
records are natural inputs for a Reppo Datanet.

**Not first — councils.** They own the duty but England's dedicated
air-quality grant fell 99.4% to £1.5M in 2024/25. Councils become *users*
first (planning officers read the construction reports), buyers later.

**Pricing hypothesis (unvalidated):** ~£50–150 per monitoring point per month,
roughly 10% of existing per-point spend.

## The product: Proof of Air

AeroLoop is not the thing that predicts. It is the **neutral referee** that
scores everyone else's predictions and corrections against reference truth that
arrives later — and certifies or pays for what holds up. Four layers:

1. **Referee.** Every prediction is saved before its truth exists and given a
   SHA-256 hash at save time; batches are anchored publicly so "before the
   truth" can be checked by anyone, not just claimed. A chronological holdout
   judges accuracy; a Reppo peer evaluation judges soundness; nothing is deleted.
2. **Subjects — a live trust map of London's sensors.** Low-cost sensors near a
   reference monitor get a live trust score (fit / drifting / unfit near action
   levels), shown in the 3D London scene. Scores come in tiers, so a sensor is
   never rated beyond what the evidence supports:
   - *Verified* — within ~500 m of an LAQN/AURN reference monitor, scored
     directly against it.
   - *Consistent* — no nearby reference; scored only on agreement with verified
     neighbours.
   - *Unrated* — not enough evidence.
3. **Competitors — a correction tournament.** Any proposer can submit a
   correction strategy: SERV-backed models, the same models without SERV,
   frontier models, TabPFN, external agents. All get the same tune data and
   are scored on the same hidden future data, across multiple windows, with
   cost per proposal recorded. This doubles as a public, unfakeable benchmark
   of OpenServ's claim that small models plus SERV match frontier models.
4. **Buyers.** A pay-per-call "verify this sensor series" service on OpenServ's
   x402 marketplace for agents, and a monthly verification appendix for
   construction-monitoring consultancies.

**Data reality (checked 2026-11-15).** Open low-cost data near London is thinner
than it looks: sensor.community had only 20 PM sensors within 20 km of central
London (3 indoor). The main source will be Breathe London (400+ Clarity nodes,
open API with a key; terms of use still to check), plus PurpleAir (paid API).
Breathe London nodes are already calibrated by their operators, so auditing them
is an independent check of an incumbent's calibration. That is the right story,
but it should be framed as collaboration, not a gotcha.

## How the product earns trust

The mechanics already in this repo are the moat — they are what make an audit
credible rather than a vendor's word:

1. **Commit before truth.** Every prediction is saved before the reference
   reading exists. No after-the-fact tuning.
2. **Chronological holdout.** Changes are proposed on a tune split and judged
   only on later data the proposer never saw.
3. **Two gates, two kinds of judgement.**
   - *Accuracy* — the holdout decides whether a correction is better.
   - *Soundness* — Reppo's peer evaluation decides whether the reasoning is
     physically plausible and not overfit (e.g. not quoting a test value).
   A change ships only if both pass.
4. **Small, auditable reasoning.** SERV Reasoning proposes changes with a
   bounded, inspectable reasoning structure — and AeroLoop measures, on hidden
   data, whether that actually beats a baseline model.
5. **Nothing is deleted.** Rejected strategies stay in the record as
   `vN-rejected`. The audit trail shows what was tried, not just what won.
6. **Independent of hardware.** Any sensor feed or model output (CAMS today)
   can be the thing under audit.

## What we deliberately are not

- **Not a sensor company.** No hardware.
- **Not a forecast API** competing with Google, Tomorrow.io or Ambee.
- **Not a certification body.** We do not issue MCERTS or CEN/TS 17660
  classifications; our reports are independent evidence that sits alongside
  formal procedures. Any comparison to directive uncertainty limits must be
  labelled indicative unless computed by the formal method.
- **Not willing to flatter a sensor.** If the evidence says a device is not fit
  for a site, AeroLoop says so. That honesty is the product.

## Where we are today (honest state, 2026-11-15)

- Working loop: predict → save → resolve truth → score → propose → holdout
  gate → keep/reject, with versioned strategies and a dashboard.
- **Milestone 1 built:** correction tournament (SERV Nano, SERV Ultra, an
  open-weight model, a heuristic; TabPFN as benchmark-only), holdout time
  windows, blind Reppo soundness gate, per-prediction SHA-256 commitments,
  daily Merkle batches with OpenTimestamps and Base anchoring, and a verify
  endpoint. Not yet exercised live: the Reppo API (no key yet) and an on-chain
  Base anchor (no wallet yet).
- Subject under audit: **CAMS model PM2.5** at four London stations — not yet
  low-cost sensor feeds, and not yet PM10.
- Real reference truth: LAQN for north_kensington (KC1), including a 192-hour
  ratified hindcast. Other stations use a labelled synthetic stand-in.
- Known limits: SERV cannot be switched off on its endpoint, so there is no
  like-for-like "same model without SERV" arm yet; repeated tournaments on the
  same history slowly tune to the holdout (live mode will fix this); TabPFN's
  licence is non-commercial, so it stays a benchmark entrant.

## Roadmap

**Milestone 1 — Referee + tournament (foundation) — built 2026-11-15**
- Proposer interface; proposers: SERV Nano, SERV Ultra, an open-weight model,
  TabPFN (benchmark-only), the deterministic heuristic. Still open: a true
  "same model without SERV" arm.
- Fair scoring: identical prompt and tune data, rolling holdout windows, cost
  and latency per proposal, leaderboard.
- Blind Reppo soundness gate on every accuracy-eligible proposal; store
  score, decision, confidence and critique.
- SHA-256 hash per prediction at save time; daily batch root anchored on
  OpenTimestamps and Base; verify endpoint.
- Remaining: first live Reppo verdict and first on-chain Base anchor; live mode
  (proposals committed now, scored on future truth).

**Milestone 2 — Real sensors and the trust map**
- Ingest Breathe London (and PurpleAir where affordable) plus LAQN/AURN
  reference sites beyond North Kensington.
- Co-location finder (≤ 500 m), trust tiers, drift detection, PM10 and the
  190 µg/m³ action-level test where PM10 exists.
- Trust layer in the 3D scene and dashboard.

**Milestone 3 — Buyers**
- Public deployment of the backend.
- x402 "verify this series" workflow on OpenServ; first real paid call.
- Exportable verification appendix (PDF/JSON) per device per period.
- 5–10 interviews with UK construction-monitoring consultancies; one design
  partner; validate per-point pricing.

**Milestone 4 — Open the tournament**
- External agents submit proposals over an API; explore a Reppo air-quality
  Datanet; EU operators ahead of directive reporting cycles.

## How we'll know it's working

- Customer: at least one consultancy says it would pay, at a stated price,
  for the verification appendix.
- Product: every shipped correction has a held-out score, a peer verdict, and a
  reproducible record.
- Integrity: zero synthetic or modelled values presented as measurements.

## Open questions

- Breathe London API terms: is commercial use and redistribution of derived
  trust scores allowed?
- How many low-cost sensors sit within ~500 m of a London reference monitor?
- Where to anchor prediction hashes publicly (Base, OpenTimestamps, or a public
  git log)?

- How many UK sites run active dust monitoring at any time? (No source found.)
- Can software correction recover sensor accuracy near 190 µg/m³, or is the
  honest answer often "not fit"? Either way, which does the buyer value more?
- What evidence format would a planning officer actually accept?
