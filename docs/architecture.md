# AeroLoop — Architecture

## Modules

- **data_sources.py** — Open-Meteo Air Quality (CAMS PM2.5/NO2) + weather. Ground truth:
  DEFRA AURN (offline stand-in for v1). Synthetic ground readings for the demo loop.
- **prediction.py** — `v1-baseline` (model + humidity correction) and `v2-improved`
  (model + humidity/wind/precip + bias). Params are versioned and agent-editable.
- **evaluation.py** — MAE, RMSE, bias on a fixed held-out benchmark; breakdown by station.
- **agent.py** — self-improvement loop: analyse errors (open-weight LLM or deterministic
  fallback) → propose new params → evaluate v2 on the same benchmark → keep only if
  improved → save new strategy version.
- **db.py** — SQLite (predictions, ground_readings, errors, strategies).
- **main.py** — FastAPI: /predict, /ground-truth, /evaluate, /self-improve, /strategies, /errors, dashboard.

## Data flow

```
Open-Meteo AQ + Weather  -->  features  -->  predict(strategy, features)  -->  save prediction
                                                                              (no ground truth yet)
ground truth arrives  -->  save reading  -->  compute error  -->  agent analyses
                                                                              -->  proposes params
                                                                              -->  evaluate v2
                                                                              -->  keep if improved
```

## Scientific constraints honoured

- CAMS/Open-Meteo output is a **model forecast**, never a measurement.
- Ground readings are **local**, not neighbourhood-representative.
- Interpolated/estimated values are never presented as measurements.
- Test-set ground truth is never used when the agent modifies its strategy.
- If the agent does not improve, it reports that honestly (v2-rejected).

## Trade-offs

- SQLite over PostGIS for v1 (speed of build). Migrate to Postgres+PostGIS for spatial queries.
- Synthetic ground readings for the offline demo loop; swap in DEFRA AURN for production.
- Open-weight model via Ollama (OpenAI-compatible) so the loop runs with no API key.
