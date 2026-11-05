---
name: pm25-strategy
description: The estimation strategy for turning CAMS model output and weather features into a ground-level PM2.5 estimate. Use it on every forecast task.
---

# PM2.5 estimation strategy

The CAMS/Open-Meteo model is a gridded forecast, but the monitor is already
assimilated into it, so it is the best estimate available.

**Rule: estimate = pm25_model × uplift.**

- Base uplift: **1.20**.
- Treat **wind_speed as already in km/h**; do not convert units.
- If **wind_speed > 20 km/h**, use uplift **1.10** instead. Stronger wind dilutes
  street-level PM2.5, so the local-source enhancement is smaller.
- If **humidity > 85%**, add **0.10** to the uplift. Very high humidity increases
  particle water uptake and can suppress vertical dispersion, raising measured
  PM2.5 relative to the model.

Other station context and weather features are secondary; do not adjust for them.
