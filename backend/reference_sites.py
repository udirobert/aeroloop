"""Empirical qualification of reference sites (LAQN, RIVM Luchtmeetnet).

LAQN's MonitoringSiteSpecies metadata is unreliable in both directions — sites
list PM2.5 they don't publish, and KC1 publishes PM2.5 without being listed.
So qualification probes EVERY open site x species against the data endpoint
and keeps those with coverage >= REFERENCE_MIN_COVERAGE (default 0.75) over
the probe window. The same rule applies to Luchtmeetnet's `components` list.

CLI:
    DATABASE_PATH=... python reference_sites.py --start 2026-11-01 --end 2026-11-09
    DATABASE_PATH=... python reference_sites.py --network luchtmeetnet --start ... --end ...
"""
from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime, timezone
from typing import Awaitable, Callable, Dict, List, Tuple

import data_sources as ds
from sensors import luchtmeetnet as lm

REFERENCE_MIN_COVERAGE = float(os.getenv("REFERENCE_MIN_COVERAGE", "0.75"))
CONCURRENCY = int(os.getenv("PROBE_CONCURRENCY", "6"))
PROBE_TIMEOUT_S = 40
RETRIES = 2
RATE_LIMIT_WAIT_S = float(os.getenv("PROBE_RATE_LIMIT_WAIT", "20"))

FetchSpecies = Callable[[str, str, datetime, datetime], Awaitable[Dict[str, float]]]


def expected_hours(start: datetime, end: datetime) -> int:
    """Inclusive-day window in hours (LAQN EndDate is inclusive)."""
    return int(((end - start).days + 1) * 24)


async def _laqn_sites() -> List[Dict]:
    return await ds.fetch_laqn_sites()


async def _luchtmeetnet_sites() -> List[Dict]:
    """NL stations normalised to the LAQN site shape (coords from detail)."""
    client = lm._client()
    try:
        stations = await lm.list_stations(client=client)
        details = await asyncio.gather(
            *(lm.fetch_station(s["number"], client=client) for s in stations))
    finally:
        await client.aclose()
    return [{**d, "date_closed": None} for d in details]


async def _probe(fetch: FetchSpecies, code: str, species: str,
                 start: datetime, end: datetime) -> Tuple[int, int]:
    """(valid_hours, expected_hours) for one site+species, with one retry."""
    last_exc: Exception | None = None
    for attempt in range(RETRIES + 1):
        try:
            data = await asyncio.wait_for(
                fetch(code, species, start, end),
                timeout=PROBE_TIMEOUT_S,
            )
            return len(data), expected_hours(start, end)
        except Exception as e:  # noqa: BLE001 — a failed probe = 0 coverage
            last_exc = e
            resp = getattr(e, "response", None)
            if resp is not None and resp.status_code == 429:
                wait = float(resp.headers.get("retry-after")
                             or RATE_LIMIT_WAIT_S)
                await asyncio.sleep(min(wait, 60))
            else:
                await asyncio.sleep(1)
    if last_exc:
        print(f"  probe failed {code}/{species}: {last_exc!r}")
    return 0, expected_hours(start, end)


# Lambdas keep late binding so tests can monkeypatch the module attributes.
_NETWORKS: Dict[str, Tuple[Callable[[], Awaitable[List[Dict]]],
                            FetchSpecies, str]] = {
    "laqn": (
        lambda: _laqn_sites(),
        lambda code, sp, s, e: ds.fetch_laqn_species(code, sp, s, e),
        "LAQN",
    ),
    "luchtmeetnet": (
        lambda: _luchtmeetnet_sites(),
        lambda code, sp, s, e: lm.fetch_measurements(code, sp, s, e),
        "Luchtmeetnet",
    ),
}


async def discover_async(start: datetime, end: datetime,
                         species: Tuple[str, ...] = ("PM25", "PM10"),
                         network: str = "laqn") -> List[Dict]:
    import db

    list_sites, fetch_species, label = _NETWORKS[network]
    sites = [s for s in await list_sites() if not s["date_closed"]]
    sem = asyncio.Semaphore(CONCURRENCY)
    probed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rows: List[Dict] = []

    async def one(site: dict, sp: str) -> None:
        async with sem:
            valid, expected = await _probe(fetch_species, site["code"], sp,
                                           start, end)
        coverage = valid / expected if expected else 0.0
        row = {
            "code": site["code"], "species": sp, "name": site["name"],
            "lat": site["lat"], "lon": site["lon"], "network": label,
            "valid_hours": valid, "expected_hours": expected,
            "coverage": coverage,
            "window_start": start.date().isoformat(),
            "window_end": end.date().isoformat(),
            "probed_at": probed_at,
            "qualifies": coverage >= REFERENCE_MIN_COVERAGE,
        }
        db.upsert_reference_site(row)
        rows.append(row)

    await asyncio.gather(*[one(s, sp) for s in sites for sp in species])
    return rows


def discover(start: datetime, end: datetime,
             species: Tuple[str, ...] = ("PM25", "PM10"),
             network: str = "laqn") -> List[Dict]:
    return asyncio.run(discover_async(start, end, species, network))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--species", default="PM25,PM10")
    ap.add_argument("--network", default="laqn",
                    choices=sorted(_NETWORKS))
    a = ap.parse_args()
    if not os.getenv("DATABASE_PATH"):
        raise SystemExit("set DATABASE_PATH")
    import db

    db.init_db()
    s = datetime.strptime(a.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    e = datetime.strptime(a.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    rows = discover(s, e, tuple(a.species.split(",")), a.network)
    for sp in a.species.split(","):
        qual = [r for r in rows if r["species"] == sp and r["qualifies"]]
        print(f"{sp}: {len(qual)} qualifying / "
              f"{sum(1 for r in rows if r['species'] == sp)} probed "
          f"({REFERENCE_MIN_COVERAGE:.0%} coverage threshold)")
        for r in qual:
            print(f"  {r['code']:6s} {r['coverage']:.0%} "
                  f"({r['valid_hours']}/{r['expected_hours']} h) {r['name']}")


if __name__ == "__main__":
    main()
