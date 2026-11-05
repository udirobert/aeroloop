---
name: pm25-strategy
description: The estimation strategy for turning CAMS model output and weather features into a ground-level PM2.5 estimate. Use it on every forecast task.
---

# PM2.5 estimation strategy

The CAMS/Open-Meteo forecast is a grid-cell average. London monitors differ by exposure, so scale it by station type and add a local traffic contribution from NO2.

**Core formula:**

```
estimate = pm25_model × uplift + no2_model × traffic_coeff
```

Then apply the weather correction and enforce `estimate ≥ 0`.

**1. Station uplifts**

- **Bloomsbury** (urban background): `0.95`
- **North Kensington** (suburban background): `0.95`
- **Westminster** (kerbside / traffic): `1.20`
- **Marylebone** (roadside / traffic): `1.05`
- Any other station: `1.10`

**2. Traffic contribution from NO2**

NO2 is a proxy for local combustion sources that add fine particles near the monitor.

- **Marylebone**: `0.12 × no2_model`
- **Westminster**: `0.06 × no2_model`
- **Bloomsbury / North Kensington**: `0.00`

**3. Weather adjustment**

- Treat `wind_speed` as already in km/h; do not convert units.
- If `wind_speed > 20 km/h`, multiply the whole estimate by `0.95`.
- Do not adjust for humidity or precipitation; their effects are already captured in the model field for these sites.

**Sanity check:** If the estimate is below 0, return `0`.
