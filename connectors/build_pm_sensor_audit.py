#!/usr/bin/env python3
"""Build ``aeroloop/pm-sensor-audit`` into a local TimeF registry.

The connector lives in-repo (``connectors/aeroloop/pm_sensor_audit``) rather
than inside ``timenet-connectors``, so this driver runs the same pipeline the
engine would: ``download -> convert -> store_dataset``.

    python connectors/build_pm_sensor_audit.py
    python connectors/build_pm_sensor_audit.py --describe

Env knobs are documented on the connector (AEROLOOP_AUDIT_DB,
AEROLOOP_PAIRS_DIR, AEROLOOP_SPECIES, AEROLOOP_MAX_PAIRS,
AEROLOOP_FORECAST_HOURS, AEROLOOP_BACKEND_DIR).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "connectors"))

from aeroloop.pm_sensor_audit import CONNECTOR  # noqa: E402
from timenet.engine import store_dataset  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=str(REPO / "connectors" / "registry"))
    ap.add_argument("--cache", default=str(REPO / "connectors" / ".cache"))
    ap.add_argument("--describe", action="store_true",
                    help="re-open the built version and describe it")
    ap.add_argument("--replace", action="store_true",
                    help="replace the committed version if it exists")
    a = ap.parse_args()

    connector = CONNECTOR()
    refs = connector.download(Path(a.cache))
    print(f"download: {len(refs)} pair(s)")
    dataset = connector.convert(refs)
    out = store_dataset(dataset, Path(a.registry), replace=a.replace)
    print(f"wrote {out}")
    if a.describe:
        from timenet import TimeNet

        with TimeNet(sources=[a.registry]).open(
                dataset.metadata.dataset_id) as reader:
            reader.read().describe()


if __name__ == "__main__":
    main()
