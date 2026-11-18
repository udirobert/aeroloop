# TimeNet hackathon — copy/paste answers

Form: https://challenge.timenet.ai/ (Round 1 closes 2026-11-22 23:59 PST)

**What would you like to build, and how will it use TimeNet?**

Cheap air-quality sensors are everywhere; trusted air-quality data is not —
sensors drift, vendors calibrate their own hardware, and the councils and
construction-dust operators who rely on the readings can't verify them. Our
project AeroLoop already audits low-cost PM sensors against official reference
monitors. For this hackathon we onboard our co-located sensor↔reference
dataset in TimeF format (records = paired audit windows, sources = low-cost
sensor + reference monitor, annotations = EPA-style verdicts and drift flags),
then fine-tune a TSLM to do what our deterministic audit can't: forecast a
sensor's next 24 hours against its reference *and* explain in plain language
whether it's drifting, over-reading, or trustworthy. The model competes in our
existing correction tournament and must beat the incumbent on a chronological
holdout it never tuned on.

**Which datasets will you use?**

- London Air Quality Network (LAQN) reference monitors —
  https://www.londonair.org.uk
- RIVM Luchtmeetnet, Netherlands — https://www.luchtmeetnet.nl
- sensor.community archive (low-cost SDS011/PM sensors) —
  https://archive.sensor.community
- Open-Meteo wind/weather covariates — https://open-meteo.com

Already ingested locally: ~22k hourly reference readings across 26 LAQN
stations plus paired sensor feeds (Oct–Nov 2026); our fetchers backfill months
more across ~1,400 registered sensors before fine-tuning.

**GitHub profile or previous work**

https://github.com/udirobert/aeroloop — live repo (dashboard + audit engine).
Profile: https://github.com/udirobert

**Would your team like to apply for Nebius compute credits?**

Yes (A)

**What would you use the credits for?**

Fine-tuning OpenTSLM variants (SoftPrompt/Flamingo, ~1–4B backbone) on our
paired sensor↔reference audit dataset — LoRA and full fine-tuning sweeps on a
single-GPU node (L40S/A100-class is plenty at this scale). The bulk goes to
evaluation: our tournament protocol runs the candidate TSLM against every
incumbent proposer across all audit windows on a chronological holdout,
repeated each iteration. Any remaining credit hosts a small inference endpoint
behind the AeroLoop audit dashboard so judges can query the fine-tuned model
live during the demo.

## Build status (as of commit)

- Connector: `connectors/aeroloop/pm_sensor_audit/` — BaseConnector, fixture
  test passing, real end-to-end build verified (download → convert →
  store_dataset → reopen).
- Corpus: 33 audit pair-windows → 66 TimeF records, 99 tasks
  (classification/answer/forecasting), 255 annotations. Labels: unfit 19,
  fit 9, drifting 3, insufficient_evidence 2.
- Backfill: `backend/backfill_audits.py --species both --weeks N` grows the
  window corpus (resumable).
