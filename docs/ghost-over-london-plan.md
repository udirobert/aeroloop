# The Ghost Over London — visual/storytelling plan

Status: Track B skeleton BUILT — /scene serves the spectral 3D city
(vendored three.js, 26k real OSM buildings, wind-advected CAMS haze,
station beacons + wisps, film mode). See docs/screenshot-scene.png.
Goal: turn AeroLoop's dashboard from an admin panel into a living simulation —
London seen from above, breathing, while the agent predicts, errs, and learns.

## The creative idea

The product's name is a loop and its metaphor is a ghost, yet neither appears
visually anywhere. The fix is one hero scene:

- **Wind made visible** — thousands of particles advected across London by the
  real wind field (earth.nullschool technique, via `leaflet-velocity`).
  Particles pick up haze colour where the modelled PM2.5 field is dense.
  This is not decoration: the strategy formula literally contains `wind_coef`
  and `precip_coef`. When the agent says "higher wind → lower PM2.5", the
  viewer watches the wind scour the ghost off the city. The physics the agent
  tunes *is* the physics animating the screen.
- **Time as the narrative axis** — scrub through a simulated/real day like a
  film: haze builds overnight, rush-hour spikes bloom, a front sweeps through
  and the ghost dissolves. Self-improvement runs are chapter markers.
- **Ghost language** — when ground truth lands, the error rises off the
  station as a spectral wisp; rejected strategies drift off the map and
  dissolve into the graveyard. The lineage becomes a spectral family tree.
- **Orbit-to-street** — open on satellite imagery over Europe (the ghost seen
  from space), descend to street level where the sensors pulse.
- **The film is the submission** — an autoplay demo mode (camera + captions +
  chapters) recorded once yields the demo video, the cover image, and the
  README hero. One asset, three jobs.

## Honesty guardrails (non-negotiable)

- Every layer labelled: haze = "modelled (CAMS via Open-Meteo)", station
  markers = "measured (LAQN)", synthetic demo data flagged as today.
- Visual drama must never outrun the data — the modelled/measured distinction
  the submission is proud of must survive into the visuals.

## Data sources (verified)

| Source | What | Auth | Use |
|---|---|---|---|
| Open-Meteo AQ + forecast | CAMS PM2.5/NO2 grid, wind u/v grid | none | haze + particles |
| LondonAir (`api.erg.ic.ac.uk`) | LAQN hourly readings, real ground truth | none | replaces synthetic |
| NASA GIBS WMTS | true-colour + aerosol/NO2 tiles, dated | none | establishing shot |
| OSM via Overpass | building footprints + road centrelines | none | Track B geometry |
| Sentinel-5P (CDSE openEO) | real TROPOMI NO2 (~5km px) | free account | optional garnish |
| Breathe London (Clarity/Airly) | 400+ hyperlocal sensors | account friction | skip for now |

## Constants

```python
# backend/data_sources.py — extend existing constants
LONDON_BBOX = {"south": 51.45, "west": -0.28, "north": 51.56, "east": -0.08}
# ~20×14 grid over inner London; ~1.3km spacing — fine for haze + wind fields
GRID_NX, GRID_NY = 20, 14

# LAQN site codes to CONFIRM at build time against
# http://api.erg.ic.ac.uk/AirQuality/Information/MonitoringSites/GroupName=London/Json
LAQN_SITE_CODES = {
    "bloomsbury":       "?",   # confirm — may be an AURN-only site
    "marylebone":       "MY1", # Marylebone Road (known kerbside site)
    "north_kensington": "KC1", # North Kensington (known site)
    "westminster":      "?",   # confirm
}
```

## Backend work

All in `backend/data_sources.py` + `backend/main.py`. Same httpx-async +
stdlib style as the existing code; in-memory cache ~15 min per grid.

### `GET /wind-field` — feeds leaflet-velocity

leaflet-velocity consumes the grib2json-style record pair used by
earth.nullschool: one record for the u-component (`parameterNumber: 2`), one
for v (`parameterNumber: 3`), data row-major starting at the **northernmost**
latitude (`la1`) moving south, each row west→east.

```python
import math
from datetime import datetime, timezone

def _uv(speed_ms: float, dir_deg: float):
    """Meteorological convention: direction is where wind comes FROM."""
    rad = math.radians(dir_deg)
    return -speed_ms * math.sin(rad), -speed_ms * math.cos(rad)  # u, v

async def fetch_wind_field() -> list:
    """One Open-Meteo call for the whole grid → leaflet-velocity record pair."""
    lats = [LONDON_BBOX["north"] - i * (LONDON_BBOX["north"] - LONDON_BBOX["south"]) / (GRID_NY - 1)
            for i in range(GRID_NY)]                          # north → south
    lons = [LONDON_BBOX["west"] + j * (LONDON_BBOX["east"] - LONDON_BBOX["west"]) / (GRID_NX - 1)
            for j in range(GRID_NX)]
    params = {
        # comma-separated lists → one HTTP call, array response
        "latitude":  ",".join(f"{v:.4f}" for v in lats),
        "longitude": ",".join(f"{v:.4f}" for v in lons),
        "hourly": "wind_speed_10m,wind_direction_10m",
        "wind_speed_unit": "ms",
        "forecast_days": 1,
    }
    rows = await _get_json(WX_URL, params)          # returns list per location
    u, v = [0.0] * (GRID_NX * GRID_NY), [0.0] * (GRID_NX * GRID_NY)
    for i, loc in enumerate(rows):                  # response order = param order
        lat_i, lon_j = divmod(i, GRID_NX)           # verify at build time!
        k = lat_i * GRID_NX + lon_j
        sp, dr = loc["hourly"]["wind_speed_10m"][-1], loc["hourly"]["wind_direction_10m"][-1]
        u[k], v[k] = _uv(sp, dr)

    def record(param_no, data):
        return {"header": {
            "parameterCategory": 2, "parameterNumber": param_no,
            "nx": GRID_NX, "ny": GRID_NY,
            "lo1": LONDON_BBOX["west"], "la1": LONDON_BBOX["north"],
            "lo2": LONDON_BBOX["east"], "la2": LONDON_BBOX["south"],
            "dx": (LONDON_BBOX["east"] - LONDON_BBOX["west"]) / (GRID_NX - 1),
            "dy": (LONDON_BBOX["north"] - LONDON_BBOX["south"]) / (GRID_NY - 1),
            "refTime": datetime.now(timezone.utc).isoformat(),
        }, "data": data}
    return [record(2, u), record(3, v)]
```

Gotchas to verify during build: (a) whether Open-Meteo returns the array in
lat-major or lon-major order — `divmod` above assumes lat-major; (b) row
order — leaflet-velocity expects `la1` = top edge. Both are one-lookup fixes.

### `GET /aq-field` — the haze

```python
async def fetch_aq_field() -> dict:
    """Same grid, hourly pm2_5 (+ no2). Frontend interpolates + colours it."""
    # identical grid params; hourly=pm2_5,nitrogen_dioxide on AQ_URL
    # return {"nx": GRID_NX, "ny": GRID_NY, "bbox": LONDON_BBOX,
    #         "pm25": [[row north→south] ...], "no2": [...],
    #         "hour_index": -1, "source": "CAMS via Open-Meteo (modelled)"}
```

### `GET /laqn-reading` — real ground truth

```python
LAQN_URL = "http://api.erg.ic.ac.uk/AirQuality"

async def fetch_laqn(site_code: str) -> dict:
    # GET {LAQN_URL}/Hourly/MonitoringIndex/SiteCode={site_code}/Json
    # → last ~24h readings; extract latest PM2.5 where the site measures it.
    # Wire into /ground-truth: real reading when LAQN responds, labelled
    # synthetic fallback when it doesn't (or when running fully offline).
    # Report which path ran — same honesty contract as params_source.
```

### `GET /scene-state` — one hydration payload

```json
{
  "stations": [{"id": "marylebone", "lat": 51.5226, "lon": -0.1546,
                "latest_pred": 18.2, "latest_actual": 21.0, "error": -2.8}],
  "strategies": [{"version": "v6", "parent": "v5", "kept": true}],
  "chapters":   [{"t": "self-improve#3", "version": "v5", "verdict": "kept"}]
}
```

### Offline mode

After each successful fetch, persist the grid to `data/cache/wind-field.json`
etc. On fetch failure, serve the cache and stamp `"source": "cached"` in the
payload so the UI can badge it. `data/` already exists and is gitignored-able.

## Frontend — Track A: Leaflet scene (the reliable deliverable)

Restructure `frontend/` → `index.html` + `app.js` + `vendor/` (leaflet 1.9.x,
leaflet-velocity — vendored, no runtime CDN). Map scene is the hero; existing
cards collapse into a side panel so nothing is lost.

### P0 — skeleton

```js
const map = L.map('scene', {
  zoomControl: false, attributionControl: false,
  preferCanvas: true,  // keeps perf sane next to the particle layer
}).setView([51.508, -0.14], 12);

// Offline-proof "basemap": vendored London boundary GeoJSON drawn as a faint
// spectral outline — more on-brand than tiles anyway.
fetch('/static/london-boundary.geojson').then(r => r.json()).then(g =>
  L.geoJSON(g, {style: {color:'#3b4a6b', weight:1, fill:false, opacity:.6}}).addTo(map));
```

### P1 — the ghost: particles + haze

```js
// Particles — the whole trick is this one layer
fetch('/wind-field').then(r => r.json()).then(wind =>
  L.velocityLayer({
    data: wind,
    velocityScale: 0.008,      // tune until streaks feel like wind, not rain
    particleAge: 90, lineWidth: 1,
    colorScale: ['#4c1d95','#7c3aed','#a78bfa','#e9d5ff'],  // spectral ramp
    opacity: 0.6,
  }).addTo(map));

// Haze — render the grid to an offscreen canvas, then let ImageOverlay's
// image smoothing bilinear-interpolate it into a soft field. Cheap + pretty.
fetch('/aq-field').then(r => r.json()).then(field => {
  const c = document.createElement('canvas');
  c.width = field.nx; c.height = field.ny;
  const ctx = c.getContext('2d'), img = ctx.createImageData(field.nx, field.ny);
  field.pm25.flat().forEach((v, i) => {
    const [r,g,b,a] = spectralPM25(v);          // PM2.5 → colour ramp
    img.data.set([r,g,b,a], i*4);
  });
  ctx.putImageData(img, 0, 0);
  L.imageOverlay(c.toDataURL(), [[field.bbox.north, field.bbox.west],
                                 [field.bbox.south, field.bbox.east]],
                 {opacity: 0.55, interactive: false}).addTo(map);
});

function spectralPM25(v) {   // WHO-ish bands → ghostly ramp; tune in art pass
  const t = Math.min(1, v / 35);                 // ~35 µg/m³ = heavy
  return [147 + t*100, 51, 234, 20 + t*160];     // faint violet → dense magenta
}
```

### P2 — the drama

- **Prediction premonition**: a marker that materialises at the station at
  predict-time — translucent, pulsing, labelled "predicted 18.2".
- **Error wisp**: when ground truth lands, spawn a CSS/canvas particle
  cluster at the station that rises and dissipates; size ∝ |error|.
  Persist a faint residue ring at big-error stations — the ghost lingers.
- **Verdict moment**: on `/self-improve` response, a stamped KEPT / REJECTED
  overlay at map centre for ~2s before the report panel updates.
- **Graveyard**: rejected strategies become small ghost sprites that drift
  with the wind field direction and fade — physically carried off by the
  same wind that carries the pollution.
- **Lineage**: the strategy table becomes a left-rail tree — kept spine
  vertical, rejections as dashed ghost branches. Pure SVG, ~80 lines.

### P3 — time scrubber

`/demo-day` already produces 24–120 hourly ticks. Extend `/aq-field` with an
optional `?hour=` so the scrubber re-fetches (or pre-fetches all 24 fields in
one `/scene-state?hours=24` payload — ~110KB, fine). On scrub: swap haze
image + re-init velocity data + move station markers. Self-improve events
render as ticks on the scrubber rail.

### P4 — film mode

```js
const FILM = [
  { t: 0,   cam: {center: [51.3, -0.5], zoom: 9},  cap: "Somewhere over the Atlantic, a ghost drifts east." },
  { t: 4,   cam: {center: [51.508,-0.14], zoom: 12}, cap: "London. 4 monitors keep watch — and one agent keeps score." },
  { t: 10,  cam: {station: "marylebone", zoom: 14}, cap: "It predicts. Then it waits for the truth." },
  // ... error wisp moment, self-improve chapter, verdict stamp, credits
];
// player: requestAnimationFrame lerp through camera keyframes, captions in a
// lower-third div; record with agent-browser / OBS → docs/cover + README GIF
```

### P5 — art pass

Real type (e.g. a hairline serif for the ghost voice + a mono for data),
spectral violet/cyan palette, drawn ghost mark replacing 👻, learning-curve
chart (holdout MAE per version; kept = solid line, rejected = ghost point).

## Track B — spectral 3D city (the ambitious version)

London as a luminous wireframe blueprint — buildings and roads as faint
spectral traces, the PM2.5 haze as the only "solid" thing in the frame. The
ghost metaphor doubles: the city is memory, the pollution is the ghost.

Design rule (non-negotiable): **real geometry, stylized surface.** OSM
footprints + road centrelines for inner London, pre-baked offline into a
vendored asset — no runtime geo fetch, offline promise survives. Stations at
true coordinates, haze geo-registered. Stylized surface, never fake data.

### B0 — geometry pipeline (offline, run once)

```python
# tools/bake_city.py — Overpass → compact vendored asset
OVERPASS = "https://overpass-api.de/api/interpreter"
QL = """
[out:json][timeout:60];
( way["building"](51.49,-0.24,51.54,-0.07);
  way["highway"~"primary|secondary|tertiary"](51.45,-0.28,51.56,-0.08); );
out geom;
"""
# → write data/london-city.json:
#   {"buildings": [{"ring": [[lon,lat],...], "h": est_height(m)}...],
#    "roads": [{"line": [[lon,lat],...], "class": "primary"}...]}
# Heights: use OSM height/levels tag when present, else hash(seed)→8–30m.
# Inner-London bbox ≈ 60–120k buildings — decimate to ~30k or bump asset
# budget; target ≤ ~8MB JSON (gzip ~2MB). Alternative free source if
# Overpass is thin: OS OpenData / London Datastore building shapefiles.
```

### B1 — the scene (three.js)

```js
// vendor three@0.1xx; ESM import via vendored module or importmap
import * as THREE from './vendor/three.module.js';

// Buildings → one merged wireframe: for each footprint ring, extrude to h,
// take edges → single LineSegments with additive ghost material.
const geo = footprintsToLineSegments(city.buildings);   // precompute in bake
const buildings = new THREE.LineSegments(geo,
  new THREE.LineBasicMaterial({color: 0x7c8cff, transparent: true,
    opacity: 0.35, blending: THREE.AdditiveBlending, depthWrite: false}));
scene.add(buildings);

// Roads → light lines on the ground plane, same material family, dimmer.

// Haze → ~8k THREE.Points in a volume above rooftops. Vertex shader advects
// each particle by /wind-field sampled per-fragment (pack u/v grid into a
// DataTexture at init — GRID_NX×GRID_NY, two channels):
//   p += sampleWind(p.xz) * dt;   alpha ∝ samplePM25(p.xz);
// particle dies → respawn upwind. That's the ghost breathing.

// Stations → vertical light shafts (additive cylinders) whose colour = live
// PM2.5 band; error wisps = small particle bursts at shaft base.

// Camera — film mode becomes trivially cinematic:
const PATH = new THREE.CatmullRomCurve3([orbit, descend, streetCanyon].flat());
// orbit (alt ~8km) → down the Strand → pull up at Marylebone for the verdict
```

### B2 — middle path (if three.js scope scares the timeline)

deck.gl needs no mapbox token when used standalone:

```js
new deck.Deck({
  initialViewState: {latitude: 51.508, longitude: -0.14, zoom: 13,
                     pitch: 60, bearing: -20},
  controller: true,
  layers: [
    new deck.PolygonLayer({                  // real footprints, extruded
      data: city.buildings, extruded: true, wireframe: true,
      getPolygon: d => d.ring, getElevation: d => d.h,
      getFillColor: [80, 90, 200, 18], getLineColor: [140, 160, 255, 120],
    }),
    new deck.PointCloudLayer({ /* haze particles */ }),
  ],
});
// + unreal bloom (postprocessing) for the glow. ~70% of Track B's look.
```

References (all MIT): `pissang/little-big-city` (real OSM → stylized 3D,
proof of tractability), `jeantimex/tokyo` (the serious version — also the
scope warning: 178 commits, has its own `performance.md`),
`greggman/cyber-web-city` (neon shader aesthetic reference),
`Makio64/dreamfold` (cool vertex-fold trick but Google tiles + Cesium Ion —
external service, clashes with local-first ethos; skip).

Cost honesty: Track B is days, not hours — geometry pipeline, shaders, perf.
Recommended structure: Track A ships first as the reliable deliverable;
Track B builds beside it against the same `/scene-state` endpoint and, if it
lands, becomes the hero + film source.

## Suggested build order

1. `/wind-field` + `/aq-field` endpoints (data exists before pixels)
2. Track A P0 skeleton + P1 ghost layer — the "wow" arrives here
3. LAQN real ground truth wired into `/ground-truth` (integrity upgrade)
4. P2 drama + lineage, P3 time scrubber
5. P4 film capture → new cover + submission assets
6. P5 art pass throughout, tightening at the end
7. Track B in parallel once step 2 proves the data plumbing

## Verification

- `GET /wind-field`, `/aq-field`, `/laqn-reading` return sane JSON (spot-check
  against Open-Meteo/LondonAir directly; check u/v sign against a known windy
  day — particles must move WITH the wind).
- Serve `uvicorn main:app --port 8000`, screenshot the scene with
  agent-browser at each phase; confirm particles advect and haze renders.
- Offline test: kill network, confirm vendored scene + cached grid still runs.
- Keep existing endpoints green — this adds, it doesn't break.

## Open questions for review

1. Replace the current dashboard outright, or keep it as a "data view" tab
   beside the scene? (Plan assumes: scene is hero, cards become a side panel.)
2. Vendored libs + cached grid keeps full offline operation but adds ~400KB
   (Track A) or ~8MB city geometry (Track B) to the repo — acceptable?
3. Sentinel-5P via a free Copernicus Data Space account for the establishing
   shot — worth the OAuth plumbing, or is GIBS good enough?
4. Film mode: real feature (autoplay + captions + scrubber choreography) or
   just screen-record the interactive scene? Feature costs more but doubles
   as a demo anyone can trigger.
5. Track B go/no-go — worth it if this is a portfolio piece, overkill if it's
   submission-week crunch. Which is it?
