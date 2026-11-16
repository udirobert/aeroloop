# Pristine Air — dashboard makeover + Daybreak Audit (plan)

Status: PLAN — for review. No code changed yet.
Scope: `frontend/index.html` drastic makeover (Pristine Air light) + optional
light-port of `frontend/scene.html` / `frontend/scene.js` (Daybreak Audit).
No backend endpoint changes. `/scene` night mode stays pristine.

North star: [`docs/vision.md`](vision.md) — AeroLoop is the independent
auditor for air-quality data. The dashboard must read as a verdict first,
evidence second, proof third — not as an admin console.

Continuity: the Ghost Over London night scene (`/scene`) is loved and stays.
Pristine Air shares its hues, voice, and simulation — daylight twin, not a
fork. See §5 for the day/night contract.

## 1. Why the current dashboard feels bland

- Everything is equal weight: map + 20 pair tiles + 8-col tournament + anchors
  + London demo all compete in the same grey `card h2 uppercase` style.
- First paint has no verdict: stat band shows counts, map shows 1,400 grey
  dots, tournament says "run to see leaderboard", scatter is empty until click.
- Jargon without translation: MAE / R² / slope 0.65–1.35 / NRMSE / lanes /
  tune n / holdout n. No plain-English sentence like "reads 2.1 high".
- Folds hide the good stuff. A reviewer who never expands a drawer leaves
  with nothing.
- Charts are crude: canvas line chart with no axes, SVG sparklines with no
  bounds, no pre-selected example.

What to keep: pair-tile → scatter "why fit/drifting/unfit" explainer (excellent),
proof-ladder concept, live counts in fold subtitles, map perf split
(`bgLayers` once + `auditLayers` per species, canvas renderer).

## 2. Creative direction

### Dashboard: air you can see

Pristine Air light. The page breathes. Background is a slow drifting particle
field — PM2.5 as soft motes. Fit air is clear, drifting/unfit air shows haze.

- **Hero is a breath test**, not a stat band. One question:
  "Is this sensor telling the truth?" + search + Try example + 1-line proof
  counts. Big inhaling circle (CSS 4s) → verdict stamps in.
- **Lung-cards with error bounds.** Reference dashed area + sensor line +
  pale band = ±RMSE (already computed). One-line verdict on every card.
- **Wind-first map.** Audit edges animate as drifting dashes in the real wind
  direction (from `/fields-timeline` wind_u/v already fetched for scene).
  Click empty map → flies to nearest audited pair.
- **Time first.** Mini hour scrubber (00→23 UTC) above the map, shared with
  scene logic. Inspired by `olwal/air` (Bay Area 4D sensor playback) and
  Aether AQI (`agentzill/aqi-dashboard`, MIT: full-viewport tinted particle
  field + glass cards per source).
- **Tournament as contenders.** 8 cols → 5 (Proposer / Δ vs incumbent /
  Won / Eligible / Gate), lane chart enlarged with legend, row expand keeps
  model/cost/latency/tokens. Winner gets KEPT stamp; losers stay as ghosts.

### Scene: Daybreak Audit (light port, same simulation)

Same `london-city.json`, same X/Z projection, same `windAt`/`pm25At`, same
FILM shots — new THEME object. Night violet-magenta haze becomes daylight
amber→brick smog; cyan beacon shafts become lighthouse beams; error wisps
become dandelion seeds. Inspired by `@takram/three-clouds` (cheap haze +
shafts), `three.js webgpu_custom_fog` (triNoise altitude-banded fog),
Codrops *The Sleepers* (lightweight `onBeforeCompile` vertical fog), and
Mumbai Air Atlas day/night edition precedent.

Day captions: "Morning. The ghost is gone — the smog remains."

## 3. Open-source references consulted

| Project | What we steal |
|---|---|
| `olwal/air` — Bay Area 4D sensor viz | time scrubber first, city/radius/date interaction |
| `agentzill/aqi-dashboard` (Aether AQI, MIT) | tint the air itself by AQI; glass cards per source |
| `Moheet10/mumbai-air-atlas` (MIT) | day/night edition precedent; inline sparklines; empirical error bounds |
| `VektorTech/air-pollution-map` | click-anywhere drill-down |
| `takram-design-engineering/three-geospatial` | Beer shadows / shafts / sparse haze as cheap toggles |
| `three.js webgpu_custom_fog` | altitude-banded triNoise fog + distance haze matched to sky |
| `terrain-fog-three.js` / Codrops Sleepers | lightweight vertical fog, instanced sprites, no raymarching |
| UGA / Harvard / Material / Highcharts a11y guides | lead with takeaway, direct labels, never color-alone, 3:1 graphics / 4.5:1 text, table fallback |

## 4. Dashboard implementation (all in `frontend/index.html`)

Single-column narrative, max-width 1080px. Order:
Hero → Verdict → Evidence (map + cards + scatter) → Contest → Proof → Demo
(demoted) → Footer. No new endpoints.

- **Tokens.** `:root` Pristine variables mapping scene hues daylight-readable:
  `--paper:#FAFBF7, --ink:#1A2B22, --air:#0E7C9E, --moss:#1B7A3D,`
  `--pollen:#B7791F, --brick:#C0392B, --beam:#7C5CF6` (kept for links/fit line).
- **Hero + verdict.** Search filters `pairCache` by uid; Try example picks
  first fit + first drifting. Sub-line from `/overview`:
  "1,426 sensors sniffed · 74 refs · last anchor {date}".
  Pre-select `rows[0]` after first `loadSensorTrust()` so scatter never empty.
- **Map daylight.** Leaflet CARTO `dark_all` → `light_all`. Keep
  `bgLayers`/`auditLayers` split. Unaudited `#D4DAD4` 2px; audited
  moss/amber/brick 6px + 1.5px edge. Tooltip copy unchanged. `fitBounds` kept.
- **Lung-cards.** Restyle `pairTile()` white, 18px radius, 4px verdict stripe.
  `sparkline()` restyle: reference `#9AA5B1` dashed area, subject `#0E7C9E`.
  Keep 5 EPA dots + titles; verdict sentence from same `failed[]/drift_flag`
  logic as `renderScatter()`.
- **Scatter.** Keep SVG math (EPA band, y=x dashed, purple fit). Container
  white, grid `#EDF0EB`. Promote existing `why` div to 15px; demote checks to
  `<details>Show EPA detail</details>`.
- **Tournament + proof.** Collapse cols, enlarge lanes to 160×40 + legend
  (solid = proposer, dashed = incumbent). Keep `togglePropDetail()`.
  `loadLadders()` becomes vertical timeline with copy-hash + Basescan links.
- **Air field.** One `<div class="air">` with 2 radial-gradient layers drifting
  40s loop, `pointer-events:none`, disabled under `prefers-reduced-motion`.
  ~20 lines CSS, zero JS.
- **Copy rewrites (only 6 strings):** header sub, coverage H2, sensor audits
  H2, tournament hint, trust H2, truthHint. Integrity strings stay verbatim
  (see §7).

## 5. Daybreak Audit port (`scene.html` / `scene.js`, ~180 lines)

- `scene.html`: light HUD CSS behind `body[data-theme=day]`, sun/moon toggle,
  `?theme=day` support. Night CSS untouched.
- `scene.js`: add `THEME = { night: {...}, day: {...} }` + `applyTheme()`:
  - `renderer.clearColor` / `scene.background` `0x02030a` → `0xEAF2F0`;
    `scene.fog` color matched to horizon (fixes #1 daylight mistake).
  - Buildings/towers/roads: `AdditiveBlending` → `NormalBlending`,
    opacity .10/.22/.16 → .28/.38/.22, colors to slate `#8AA0B5/#4A6B8A`;
    add ground plane `#DDE8E4` + `HemisphereLight(.9)` + `DirectionalLight`.
  - Haze: keep 15k points + `windAt` advection; retune `size 105→70`,
    `opacity .6→.42`, `spectral(t)` `HSL .78→.66` → daylight
    `HSL .13→.02` amber→brick; add altitude fade (low denser).
  - Beacons: `CylinderGeometry` opacity .3→.12, color `#67e8f9`→`#0E7C9E`;
    rings same. Wisps: same `seed/ph` rise math, color warm grey,
    `NormalBlending`.
  - `textSprite()`: white + black shadow → ink `#1A2B22` + white halo
    (`strokeText`). Bloom `0.55→0.15`, threshold up.
  - Toggle: HUD button + `?theme=` + auto from `prefers-color-scheme`;
    800ms CSS overlay cross-fade, no simulation reset. `?capture` path keeps
    working for video (force night unless `&theme=day`).
  - Film captions get day variants; camera shots unchanged.

## 6. Build order + acceptance

0. Tokens (variables only, no visual change).
1. Dashboard shell: hero + breath + verdict + single column. Pass: verdict
   visible <2s on cached `/map-data`, all fetches 200, old IDs intact.
2. Evidence: daylight map + lung-cards + auto-select + mini-scrubber. Pass:
   species toggle re-tints without refetch.
3. Daybreak port (separate diff). Pass: `?theme=day|night` both film-clean,
   same hours, same cameras.
4. Contest + proof polish. Pass: ghost rows kept, OGL footer present.
5. A11y + perf. Pass: AA contrast, keyboard tiles/scrubber, table fallback
   for scatter, haze stays 15k, no new textures.

## 7. Integrity guardrails (non-negotiable)

- Synthetic readings stay labelled `synthetic` in DB + API `source`.
- Holdout split never used for tuning — hero sub says "scored on future data
  it never tuned on".
- Rejected strategies recorded, never deleted — ghosts stay proud.
- `committed_at` is self-reported; only anchor time publicly proven. Never
  describe `hindcast`/`simulated` rows as pre-truth.
- EU uncertainty comparisons labelled *indicative*; no MCERTS/CEN claims.
- Reference sites qualify by probing (≥75% hours), never LAQN metadata.
- Any Breathe London values carry: "Contains Breathe London data licensed
  under the Open Government Licence v3.0" linking https://www.breathelondon.org/.
- Trust statuses compare vs US EPA 24h targets, indicative not certification;
  drift flag is AeroLoop heuristic.
- Market numbers trace to `docs/research/positioning-2026-11.md`; pricing as
  hypothesis.
- Media: no video files committed (gitignored); YouTube links only.
- Tests/smoke runs use temp `ANCHORS_DIR` + `DATABASE_PATH`.
