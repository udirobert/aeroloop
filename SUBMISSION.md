---
title: "AeroLoop — the air-quality agent that keeps its own ghosts 👻"
published: false
tags: devchallenge, hf26challenge, opensource, ai
cover_image:
---

*Hacktoberfest Week 4 — "Ghost in the Machine"*

AeroLoop is a self-improving agent that predicts PM2.5 air pollution over London.
Every prediction is saved **before** ground truth exists. When the real reading
arrives, the agent scores itself, hunts for patterns in its own errors, rewrites
its own estimation strategy — and then does something most "self-improving" demos
never do: it tries to prove, on data it has never seen, that it actually got better.

## The ghost

Air pollution is already a ghost story. PM2.5 is the invisible residue of traffic,
heating and weather that lingers in a city long after the source is gone — measured
now, gone tomorrow, shaping lungs for years.

But AeroLoop's ghost is somewhere else: **inside the machine**. The agent's memory
is a versioned strategy file. Every idea it ever had — including the ones that
failed — stays in the record. Rejected strategies are saved as `v3-rejected` and
rendered on the dashboard as literal ghosts 👻: dimmed, italic, still part of the
lineage. The machine doesn't just learn; it remembers what didn't work, and you
can audit every step of how it changed.

## How the loop works

```
predict (features available NOW only)  →  save prediction, no ground truth
ground truth arrives later             →  matched pair (predicted, actual)
self-improve:
  tune split (earlier ~2/3, chronological)
      → open-weight model reads the errors, proposes prose + new params
  holdout split (later ~1/3 — never touched by tuning)
      → score incumbent vs candidate
  keep if holdout MAE improves, else record vN-rejected
```

The strategy itself is a small, inspectable linear correction over the CAMS model
output:

```
pred = pm25_model + humidity_coef*(h-50) + wind_coef*(w-5) + precip_coef*mm + bias
```

Small models hallucinate confidently, so anything the LLM proposes is clamped to
sane bounds and — crucially — **must beat the incumbent on the holdout split**.
The LLM is the imagination; the holdout is the judge. If the model can't be
reached or returns junk, a deterministic heuristic proposes instead, and the
report says exactly which path ran (`model_used`, `params_source`). No silent
fallbacks.

## What actually happened

One demo session: a simulated London day (4 stations × 30 hourly ticks, 120
matched prediction/reading pairs), real reasoning from real open-weight models.

| Version | Proposed by | Change | Holdout MAE | Verdict |
|---------|-------------|--------|-------------|---------|
| v3 | `nemotron-mini` (local Ollama) | "increase humidity_coef by 0.05" — it was already −0.05; a no-op | no gain | **rejected** → ghost |
| v4, v5 | heuristic fallback (model output unusable, reported honestly) | bias corrections | 4.12 → 3.15 → 3.17 | kept |
| v6–v8 | `nemotron-mini` | sensible prose, params that made things worse | — | **rejected** → ghosts |
| v9 | `gemma-3-27b-it` | fluent diagnosis of under-prediction… then proposed *reducing* bias — wrong direction | 3.17 → 4.58 | **rejected** → ghost |
| v10 | `gemma-3-27b-it` | raise bias 4.36 → 4.6, soften humidity/wind corrections | 3.17 → **2.84** | **kept** |

The honest bits are the fun bits. The first proposal ever was a no-op dressed up
as an improvement — the holdout gate caught it. Later, a 27B model wrote a
*beautifully reasoned* analysis of systematic under-prediction and then proposed
moving the bias the wrong way; the gate caught that too. The LLM is the
imagination; the holdout is the judge; the graveyard of ghosts (v3–v9) is the
audit trail.

[DASHBOARD SCREENSHOT: docs/screenshot-full.png]

## Why open innovation mattered here

- **It runs with the lights (and the internet) off.** The reasoning core is an
  open-weight model — `nemotron-mini` on Ollama for a fully local, zero-cost
  loop, or hosted **Gemma** (`gemma-3-27b-it`, via Hugging Face's OpenAI-compatible
  router; `gemma-4` on OpenRouter as a documented fallback). One env var
  switches; the strategy record logs *which* model produced each version, so
  swapping brains is an auditable act, not a config shrug.
- **A real model-chain, honestly reported.** AeroLoop tries hosted Gemma, falls
  back to a second Gemma endpoint, then to local Ollama — and every report says
  exactly which model (or which fallback) produced the change. Several rows in
  the table above exist *because* the system admitted it fell back.
- **The agent's memory is a SQLite file on my machine.** Predictions, ground
  readings, every strategy ever proposed — nothing lives on someone else's
  server. If every vendor disappeared tomorrow the ghost would still be there.
- **Open APIs all the way down:** Open-Meteo (no key) for CAMS PM2.5 + weather,
  an OpenAI-compatible endpoint for reasoning, plain JSON on disk for memory.
- **Challengers welcome:** the holdout gate doesn't care what a candidate is.
  Plug in **TabPFN** (Prior Labs' open-weight tabular foundation model) and it
  gets scored on the same unseen data as the linear formula — foundation model
  vs. a 4-coefficient formula, judged by the same rules.

## Scientific integrity, enforced in code

- CAMS/Open-Meteo output is a model forecast, never presented as a measurement.
- The holdout is chronological and untouched by tuning — no leakage.
- Demo ground truth is a deterministic synthetic stand-in (labelled `synthetic`
  in the DB); swap in DEFRA AURN for production.
- If the agent doesn't improve, it says so — and keeps the rejection as evidence.

## Try it

[REPO LINK]

```bash
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && cp ../.env.example .env
uvicorn main:app --port 8000
# dashboard → "Simulate 24h" → "Self-Improve"
```

`POST /demo-day` gives the agent a day of memories fully offline; `POST
/self-improve` runs the whole analyse → propose → holdout-gate → keep/reject loop.

## What's next

- Real DEFRA AURN ground truth (the synthetic stand-in is honest scaffolding)
- Serve the winning TabPFN strategy for live predictions, not just audit
- Sentinel-5P / AOD satellite features as a second opinion

---

*Built for the Hacktoberfest Open-Source AI Challenge, Week 4: Ghost in the
Machine. Open-weight reasoning (Gemma / nemotron-mini via Ollama), open data
(Open-Meteo), open everything.*
