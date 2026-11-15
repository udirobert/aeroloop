# AeroLoop — OpenServ Hackathon 2 submission

**Track: Open** ("Bring your own idea and build it on SERV Reasoning. Any domain, any stack.")
**Repo:** https://github.com/udirobert/aeroloop · **Demo video:** [https://youtu.be/LqHMPDhwT1o](https://youtu.be/LqHMPDhwT1o) (~78 s, narrated with word-synced captions)
**Live demo:** `cd backend && uvicorn main:app --port 8000` → http://localhost:8000

## The project

AeroLoop is an independent auditor for air-quality data. It takes a cheap, drifting
source of PM2.5 (here: the CAMS model) and corrects it against a reference monitor,
then **proves every correction on a chronological holdout it never tuned on** and
keeps an audit trail that includes the ideas it rejected. The first market is UK
construction/demolition dust monitoring, where Section 61 consents already require
continuous PM10 monitoring and the developer pays; from 12 Dec 2026 the revised EU
Ambient Air Quality Directive (2024/2881) sets numeric uncertainty limits for every
type of evidence. What is missing is an independent party that produces *proof* a
correction is valid. That is the product.

The agent loop: predict → store the prediction with its inputs → receive delayed
reference truth → score itself → propose a correction → re-score on the holdout →
ship only if it genuinely improves, otherwise keep the attempt as a `vN-rejected`
ghost.

## How SERV Reasoning is used

SERV is not a wrapper around one call. It is the **correction engine**, entered into
a tournament against non-SERV baselines under identical conditions.

1. **Two SERV tiers compete in every tournament.** `serv-nano` and `serv-ultra`
   ([`backend/proposers.json`](backend/proposers.json)) hit the same endpoint
   (`https://inference-api.openserv.ai/v1`) with **byte-identical messages** —
   enforced by `test_all_llm_proposers_get_identical_messages_with_system`. Model
   ids and per-token prices were verified against `GET /v1/models` on 2026-11-15.
2. **A static system contract, statistics in the user message.**
   [`backend/agent.py:98`](backend/agent.py#L98) is a constant describing the bounded
   parameter space and the audit rules; all error statistics go in the user message
   ([`build_messages`](backend/agent.py#L128)). SERV's BRAID reasoning graph is cached
   per organisation keyed on the system prompt, so a constant system prompt is
   cache-eligible on every call by construction.
3. **SERV's task is bounded and auditable.** Read the incumbent's errors on the
   *tune* split; return a parameter correction inside `PARAM_BOUNDS` plus a
   four-part written rationale (what went wrong / pattern / change / why it helps).
   Holdout timestamps never appear in the prompt
   (`test_prompt_has_no_holdout_leakage`).
4. **Schema-drift normalisation.** SERV returns a different JSON shape on identical
   prompts. We identify the params object by *the parameter space it contains*, not
   its key name ([`_params_by_content`](backend/agent.py#L185)), skipping decoy
   `current_params` echoes, and map prose aliases
   ([`_canonical_analysis`](backend/agent.py#L207)).
5. **Provider evidence is persisted per proposal** — response id, `finish_reason`,
   prompt/completion tokens, cost at verified list prices, and the observed response
   schema — in `proposals.provider_evidence`
   ([`backend/db.py`](backend/db.py)), and rendered in the dashboard leaderboard.
6. **SERV gets no privilege.** Its proposals pass the same gate as the deterministic
   heuristic and the open-weight baseline: better whole-holdout MAE **and** a strict
   majority of the 3 chronological sub-windows
   ([`backend/agent.py:657`](backend/agent.py#L657)). A Reppo peer soundness verdict
   is wired for accuracy-eligible proposals ([`backend/reppo.py`](backend/reppo.py)).

## What we measured

### A. Real reference truth — LAQN North Kensington (KC1)

192 ratified hourly PM2.5 readings, 2026-11-01T00:00 → 2026-11-08T23:00 UTC,
measured range **2.5–103.8 µg/m³**. Tune = first 128 h; holdout = last 64 h
(2026-11-06T08:00 → 2026-11-08T23:00), split into 3 windows. Every reading is
labelled `LAQN KC1 ratified reference PM2.5` in the DB and API.

| Strategy | Holdout MAE (µg/m³) | Holdout bias | Whole-set MAE |
|---|---|---|---|
| v1-baseline (raw CAMS) | 23.269 | −22.653 | 9.995 |
| v2-improved (starting incumbent) | 21.047 | −19.552 | 9.598 |
| v3 (tournament run 1 winner) | 20.510 | −18.795 | 9.231 |
| v4 (tournament run 2 winner) | 20.234 | −18.392 | 9.149 |

CAMS genuinely under-reads this monitor. Two accepted corrections cut holdout MAE
**13.0%** from raw CAMS (23.269 → 20.234).

Run 2, incumbent v3 (holdout MAE 20.510), all proposers on the same prompt/holdout:

| Proposer | SERV | Holdout MAE | Windows | Cost | Outcome |
|---|---|---|---|---|---|
| open-weight (Gemma-3-27b, HF) | no | **20.234** | 3/3 | local | winner → v4 |
| serv-nano | **yes** | 20.407 | 3/3 | **$0.000726** | eligible |
| heuristic | no | 20.770 | 0/3 | $0 | rejected |
| tabpfn | no | 26.856 | 0/3 | — | ineligible (predictor) |
| serv-ultra | **yes** | — | — | $0.028698 | **content-filter refusal** |

### B. What the reasoning tier costs — same prompt, same holdout

Synthetic-labelled audit (120 pairs, clearly marked `synthetic demo (offline
stand-in)`), run 4, incumbent MAE 2.947:

| Proposer | Holdout MAE | Latency | Cost |
|---|---|---|---|
| serv-nano | 2.938 | 4 273 ms | **$0.000971** |
| serv-ultra | 2.939 | 11 036 ms | **$0.020917** |

**21.5× the cost, 2.6× the latency, ΔMAE 0.001.** No proposal won a strict majority
of windows *and* beat the incumbent overall, so the gate shipped nothing and kept
`v11-rejected`. Run 3 on real truth repeated the pattern at 15.6× ($0.001406 vs
$0.021905) with serv-ultra *worse* (21.200 vs 20.036).

OpenServ Labs' [BRAID paper](https://arxiv.org/html/2512.15959v1) reports up to 74×
performance-per-dollar, and a beta user's benchmark reports ~100× cheaper per call
([vendor write-up](https://www.openserv.ai/blog/braid-is-the-missing-piece-in-ai-reasoning));
neither has been independently reproduced. Our independent result on this task is
narrower and more useful: **the small SERV tier is the cost-effective one; upgrading
the tier bought no accuracy here.** That is exactly the kind of claim an auditor
should make about its own tooling.

### C. The 26-site stress test — where the honest answer is "not yet"

Milestone 2a widened the audit from one monitor to **26 LAQN reference sites**
qualified by probing their data (≥75% of hours present), over 40 days
(2026-10-01 → 2026-11-08): **22,309 matched pairs**, 7,437 of them on the
chronological holdout. Evidence:
[`submission/evidence/real-audit-multisite.json`](submission/evidence/real-audit-multisite.json).

- Raw CAMS under-reads at **all 26 sites** (holdout bias negative everywhere;
  overall holdout MAE 10.590 µg/m³, bias −7.068).
- The strategy can now *scale* CAMS as well as shift it. The multisite tournament
  winner (open-weight) cuts overall holdout MAE to 10.156 — **4.1%**, better at
  22 of 26 sites. Scored against US EPA 24-hour targets by the trust engine
  ([`backend/trust.py`](backend/trust.py), indicative, not certification), every
  site still fails: an offset-and-scale correction cannot repair a model that
  under-responds by roughly half. We publish that failure rather than hide it.
- On this prompt **both SERV tiers were refused by the content filter** and still
  billed ($0.001448 nano, $0.034892 ultra):
  [`submission/evidence/tournament-multisite-scale-run1.json`](submission/evidence/tournament-multisite-scale-run1.json).
  The refusals are recorded as named failure modes, not retried with the filter
  disabled.

This is the product thesis in one table: cheap air-quality evidence is widely
unfit, and the scarce good is an independent, holdout-proven statement of *how*
unfit — including when our own correction is not enough.

### D. The Reppo soundness gate — wired, verified live, not yet triggered

Every accuracy-eligible proposal is sent to Reppo for a blind peer review
(proposer name and model are hidden). The gate is verified against the live API
(one standalone evaluation on 2026-11-15: `accept`, score 100, routed to
`review` at medium confidence, about 90 s). In the recorded tournaments it has
not yet fired on a real proposal: runs 1–4 predate the key, and a live run with
the key ([`submission/evidence/tournament-real-run5-reppo.json`](submission/evidence/tournament-real-run5-reppo.json))
produced no accuracy-eligible proposal (best was serv-nano at 19.926 vs the
incumbent's 19.747), so the change was recorded as a ghost and nothing was sent
for review.

## Reliability findings (engineered around, not hidden)

- A system/developer message is **mandatory**; omitting it returns HTTP 400.
- `max_tokens` is rejected; the endpoint requires `max_completion_tokens`
  (per-proposer `token_param` in `proposers.json`).
- **Output schema is non-deterministic** across identical prompts: ≥6 shapes
  observed (`proposed_params`, `updated_params`, `new_params`,
  `proposed_parameters`, plus prose-only variants), some echoing a decoy
  `current_params`. Handled by content-based extraction, covered by tests.
- **Intermittent content-filter refusal of a benign scientific prompt**:
  `finish_reason: "content_filter"`, body `"I can't share that."`, still billed
  (run 2: 1010+681 tokens, $0.028698, response `msg_011Ch5QQQdCgLqp8Tc7179mg`).
  The `serv_*` tool surface exposes `disable_content_filter`; **we deliberately did
  not disable it.** The refusal is recorded as a named failure mode in the
  leaderboard and the audit trail.
- `usage` exposes no prompt-cache detail (`cached_tokens` absent) and
  `reasoning_tokens: 0`, so the BRAID generator call is not itemised. Our cost
  figures are solver-call costs at list price, not all-in SERV costs.

## Limitations (stated, not buried)

- **Hindcast, not pre-registered.** `backfill_laqn.py` recomputes predictions from
  archived inputs over already-ratified hours. The "committed before truth existed"
  guarantee applies to the live `/predict` path, not to this audit.
- **Holdout reuse across runs.** Each run's tuning never touches that run's holdout,
  but repeated tournaments on the same 192 hours reuse the same holdout for
  *selection*, so v3/v4 holdout scores are selection-optimistic. v1/v2 are the honest
  out-of-sample numbers. The fix is a rolling holdout over fresh ratified hours.
- Only KC1 publishes hourly PM2.5 in LAQN; the other three stations remain labelled
  synthetic and are never presented as measurements.
- The Reppo soundness gate reports `not_configured` without `REPPO_API_KEY`;
  eligible proposals are still kept, honestly labelled.
- Comparisons to EU directive uncertainty limits are **indicative**; we issue no
  MCERTS/CEN classification.

## Reproduce

```bash
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && cp ../.env.example .env   # add SERV_API_KEY
uvicorn main:app --port 8000                                 # dashboard
python -m pytest -q                                          # 32 tests
# real-reference audit (separate DB; never mixed with synthetic):
DATABASE_PATH=../data/aeroloop-laqn.db python backfill_laqn.py --start 2026-11-01 --end 2026-11-09
DATABASE_PATH=../data/aeroloop-laqn.db uvicorn main:app --port 8001
curl -X POST localhost:8001/tournament
DATABASE_PATH=../data/aeroloop-laqn.db python score_real_audit.py
```

Evidence artifacts: [`submission/evidence/`](submission/evidence/) — full tournament
JSON for real runs 1–3 and synthetic run 4, plus the per-strategy holdout score table.

## Deliverables

- Public repo: https://github.com/udirobert/aeroloop
- Demo video: https://youtu.be/LqHMPDhwT1o — 78 s landscape film. Narration:
  ElevenLabs `eleven_v4`, shared-library voice "Maria – Warm, Sophisticated
  Londoner"; captions are word-synced from the TTS character alignment; ambient
  bed from ElevenLabs sound-generation. Motion-design scenes are interleaved with
  real dashboard footage, and every live-action segment carries an on-screen
  provenance tag (real LAQN KC1 ratified hours vs the synthetic-labelled cost
  audit), so no modelled or synthetic number is ever presented as a measurement.
  The earlier silent captioned cut stays in git history (`b60ab16`); per
  `AGENTS.md` no additional video files are tracked.
- This write-up: `SUBMISSION-OPENSERV.md`
- X post: [`submission/x-post.md`](submission/x-post.md) (link added to the form on posting)