#!/usr/bin/env python3
"""Bake OSM buildings + roads for the Ghost Over London scene.

Fetches OpenStreetMap geometry via Overpass once, decimates/simplifies it, and
writes a compact vendored asset: frontend/london-city.json. The scene reads it
as a static file — no runtime geo fetch, so the offline promise survives.

Usage:  python3 tools/bake_city.py
"""
import hashlib
import json
import os
import random
import urllib.parse
import urllib.request

try:
    import httpx
except ImportError:
    httpx = None

OVERPASS = "https://overpass-api.de/api/interpreter"
# S, W, N, E — covers all four stations plus margin for the flythrough
BBOX = (51.488, -0.245, 51.542, -0.085)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "london-city.json")
MAX_BUILDINGS = 26000

QL = f"""
[out:json][timeout:180];
(
  way["building"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["highway"~"primary|secondary|tertiary|residential"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
);
out geom;
"""


def ring_area(ring):
    """Shoelace area in deg² (good enough for decimation ranking)."""
    a = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2


def simplify(ring, keep=2):
    """Drop every `keep`-th interior vertex of big rings; close the ring."""
    if len(ring) <= 8:
        return ring
    core = [ring[0]] + ring[1:-1:keep]
    core.append(core[0])
    return core


def est_height(tags, ring):
    h = tags.get("height")
    if h:
        try:
            return min(220.0, float(str(h).split()[0].replace(",", ".")))
        except ValueError:
            pass
    lv = tags.get("building:levels")
    if lv:
        try:
            return min(220.0, float(lv) * 3.0)
        except ValueError:
            pass
    # deterministic pseudo-random by centroid so the skyline is stable
    cx = sum(p[0] for p in ring) / len(ring)
    cy = sum(p[1] for p in ring) / len(ring)
    seed = int(hashlib.md5(f"{cx:.6f}|{cy:.6f}".encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    return rng.uniform(8, 26) + (rng.random() ** 8) * 90  # rare towers


def main():
    print("querying Overpass (buildings + roads over inner London)…")
    headers = {"User-Agent": "aeroloop-ghost-city-bake/1.0"}
    if httpx:  # venv python — certifi SSL works
        osm = httpx.post(OVERPASS, data={"data": QL}, headers=headers, timeout=240).json()
    else:
        req = urllib.request.Request(
            OVERPASS,
            data=f"data={urllib.parse.quote(QL)}".encode(),
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=240) as r:
            osm = json.loads(r.read())

    buildings, roads = [], []
    for el in osm.get("elements", []):
        geom = el.get("geometry")
        if not geom or len(geom) < 3:
            continue
        tags = el.get("tags", {})
        pts = [[round(p["lon"], 6), round(p["lat"], 6)] for p in geom]
        if "building" in tags:
            if pts[0] != pts[-1]:
                pts.append(pts[0])
            ring = simplify(pts)
            buildings.append({"ring": ring, "h": round(est_height(tags, ring), 1)})
        elif "highway" in tags:
            roads.append({"line": pts, "class": tags["highway"]})

    # decimate: keep every big building, sample the rest down to the cap
    if len(buildings) > MAX_BUILDINGS:
        areas = [(ring_area(b["ring"]), i) for i, b in enumerate(buildings)]
        areas.sort(reverse=True)
        keep = {i for _, i in areas[: MAX_BUILDINGS // 2]}
        rest = [i for _, i in areas[MAX_BUILDINGS // 2:]]
        random.Random(11).shuffle(rest)
        keep.update(rest[: MAX_BUILDINGS - len(keep)])
        buildings = [b for i, b in enumerate(buildings) if i in keep]

    out = {"bbox": {"south": BBOX[0], "west": BBOX[1], "north": BBOX[2], "east": BBOX[3]},
           "source": "OpenStreetMap via Overpass (ODbL)",
           "buildings": buildings, "roads": roads}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    mb = os.path.getsize(OUT) / 1e6
    print(f"wrote {OUT} — {len(buildings)} buildings, {len(roads)} roads, {mb:.1f}MB")


if __name__ == "__main__":
    main()
