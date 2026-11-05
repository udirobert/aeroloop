---
name: pm25-strategy
description: The estimation strategy for turning CAMS model output and weather features into a ground-level PM2.5 estimate. Use it on every forecast task.
---

# PM2.5 estimation strategy

The CAMS/Open-Meteo model is a gridded forecast, but the monitor is already
assimilated into it, so it is the best estimate available.

**Rule: estimate = pm25_model, unchanged.**

Weather and station context are secondary; do not adjust for them.

<!--
This strategy is deliberately simple. The improve step (npm run improve) asks
the agent to add, sharpen or remove rules here based on the errors the scorer
reported in its last run: systematic under- or over-reads, station effects,
weather effects.
-->
