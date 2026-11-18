"""Backfill sensor-vs-reference audits over many historical windows.

One ``sensor_audits`` row per (uid, species, window) is one TimeNet record —
growing the fine-tuning corpus means re-running the audit over more windows,
not more code. Each call to ``sensor_audit.audit`` re-derives the verified
co-located candidates, fetches sensor.community archive CSVs + the RIVM
reference for the window, scores with the trust engine, and upserts — so a
window can be re-run safely and a killed run resumes where it stopped.

    DATABASE_PATH=../data/aeroloop.db python backfill_audits.py \
        --species both --end 2026-11-09 --weeks 12 --window-days 8

Windows are non-overlapping blocks of ``--window-days`` days ending at
``--end`` (or between ``--start``/``--end``). A window with an existing
``sensor_audits`` row for that species is skipped; ``--force`` re-audits it.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import db
import sensor_audit

WINDOW_SPACING_S = 2.0


def _windows(start: datetime, end: datetime, days: int) -> List[tuple]:
    """Non-overlapping [s, e) day-aligned windows of `days` days."""
    out = []
    e = end
    while e - timedelta(days=days) >= start:
        s = e - timedelta(days=days)
        out.append((s, e - timedelta(days=1)))  # audit treats bounds as dates
        e = s
    return out


def _audited_windows(species: str) -> set:
    """(window_start, window_end) pairs already in sensor_audits."""
    return {(a["window_start"], a["window_end"])
            for a in db.get_sensor_audits(species=species)}


async def backfill(species: str, windows: List[tuple], force: bool,
                   out_dir: str | None) -> Dict[str, int]:
    done = _audited_windows(species)
    counts: Dict[str, int] = {}
    for s, e in windows:
        key = f"{s.date().isoformat()}..{e.date().isoformat()}"
        if not force and (s.date().isoformat(), e.date().isoformat()) in done:
            print(f"  {key}: already audited — skipped")
            counts[key] = 0
            continue
        rep = await sensor_audit.audit(species, s, e)
        counts[key] = len(rep["results"])
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(
                out_dir, f"sensor-audit-{species}-{s.date()}_{e.date()}.json")
            with open(path, "w") as f:
                json.dump(rep, f, indent=2)
        await asyncio.sleep(WINDOW_SPACING_S)
    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--species", default="PM25",
                    choices=["PM25", "PM10", "both"])
    ap.add_argument("--window-days", type=int, default=8,
                    help="audit window length (8d = 7d context + 24h forecast)")
    ap.add_argument("--end", default=None,
                    help="window end date YYYY-MM-DD (default: today UTC)")
    ap.add_argument("--weeks", type=int, default=None,
                    help="how many weeks of history to cover")
    ap.add_argument("--start", default=None,
                    help="explicit earliest date YYYY-MM-DD (overrides --weeks)")
    ap.add_argument("--out", default=None, help="evidence JSON output dir")
    ap.add_argument("--force", action="store_true",
                    help="re-audit windows that already have rows")
    a = ap.parse_args()
    if not os.getenv("DATABASE_PATH"):
        raise SystemExit("set DATABASE_PATH")
    db.init_db()

    end = (datetime.strptime(a.end, "%Y-%m-%d") if a.end
           else datetime.now(timezone.utc).replace(hour=0, minute=0,
                                                   second=0, microsecond=0))
    if a.start:
        start = datetime.strptime(a.start, "%Y-%m-%d")
    elif a.weeks:
        start = end - timedelta(weeks=a.weeks)
    else:
        start = end - timedelta(weeks=4)
    start = start.replace(tzinfo=timezone.utc)
    end = end.replace(tzinfo=timezone.utc)

    windows = _windows(start, end, a.window_days)
    species = ["PM25", "PM10"] if a.species == "both" else [a.species]
    print(f"{len(windows)} windows x {species} "
          f"({windows[-1][0].date()} .. {windows[0][1].date()})")
    for sp in species:
        print(f"== {sp} ==")
        counts = asyncio.run(backfill(sp, windows, a.force, a.out))
        audited = {k: v for k, v in counts.items() if v}
        print(f"{sp}: {len(audited)} windows audited, "
              f"{sum(audited.values())} pair-windows "
              f"({len(counts) - len(audited)} skipped) "
              f"into {os.environ['DATABASE_PATH']}")


if __name__ == "__main__":
    main()
