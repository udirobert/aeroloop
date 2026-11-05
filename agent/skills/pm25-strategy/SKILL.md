---
name: pm25-strategy
description: The estimation strategy for turning CAMS model output and weather features into a ground-level PM2.5 estimate. Use it on every forecast task.
---

# PM2.5 estimation strategy

The CAMS/Open-Meteo model is a gridded forecast, but the monitor is already
assimilated into it, so it is the best estimate available.

**Rule: estimate = pm25_model + 2.0**

This correction applies to all stations and times.
-->
