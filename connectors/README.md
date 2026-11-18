# AeroLoop → TimeNet

Connector for the [TimeNet](https://github.com/OpenTSLM/TimeNet) hackathon:
exports AeroLoop's co-located PM audit corpus as a TimeF dataset
(`aeroloop/pm-sensor-audit`), ready to fine-tune a TSLM (e.g. OpenTSLM).

## Layout

```
connectors/
  aeroloop/pm_sensor_audit/   # the BaseConnector — mirrors timenet-connectors'
                            # datasets/<org>/<name>/ layout for upstreaming
    connector.py              # download -> convert
    dataset.yaml              # the card
    tests/                    # fixture-based, no network
  build_pm_sensor_audit.py    # driver: download -> convert -> store_dataset
  registry/                   # build output (gitignored)
  .cache/                     # materialized pair JSONs (gitignored)
```

## What the dataset looks like

One audit window (`sensor_uid × species × window`, keyed like
`sensor_audits`) becomes:

- an **audit-context record** — the low-cost sensor and its reference monitor
  over the first `window − 24h`, annotated with the audit verdict (indicative
  EPA checks, slope/r²/RMSE/bias, drift flag, co-location distance), carrying
  - `ClassificationTask` — trust status ∈ {fit, drifting, unfit,
    insufficient_evidence} (`trust.py`),
  - `AnswerTask` — a plain-language verdict plus an evidence rationale;
- a **forecast-target record** — the final 24h of the reference series,
  answer to the `ForecastingTask` on the context record.

The verdict label describes the full audit window; the classification input
stops before the forecast horizon so the model answers from history only.

## Build

```bash
python -m venv connectors/.venv && source connectors/.venv/bin/activate
pip install timenet httpx
python connectors/build_pm_sensor_audit.py --describe
# offline rebuild (no API calls): point at collected pairs
AEROLOOP_PAIRS_DIR=connectors/.cache python connectors/build_pm_sensor_audit.py
```

Sources: sensor.community archive CSVs (sensor series), RIVM Luchtmeetnet
open API and LAQN (reference series — always fetched live, the snapshot
stores verdicts not reference hours). The reference fetch needs network on
first build; pair JSONs in `.cache` make rebuilds offline.

## Growing the corpus

`backend/backfill_audits.py` extends `sensor_audits` backwards over sliding
windows, reusing `sensor_audit.audit` verbatim — so connector and dashboard
stay in lockstep. Resumable: skips pair-windows already audited.

```bash
cd backend
DATABASE_PATH=../data/aeroloop.db python backfill_audits.py \
    --weeks 12 --species both
# then rebuild the dataset (picks up the new windows)
python ../connectors/build_pm_sensor_audit.py --replace --describe
```

## Test

```bash
python -m pytest connectors/aeroloop/pm_sensor_audit/tests -q
```

## Data sources & licence

Mixed provenance — sensor.community archive, LAQN (api.erg.ic.ac.uk), RIVM
Luchtmeetnet open API, Breathe London (OGL v3, needs `BREATHE_LONDON_API_KEY`).
Card declares `OTHER`; check each upstream licence before publishing the
built dataset.
