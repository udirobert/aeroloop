"""Daily anchor job: build yesterday's Merkle batch, then OTS + Base.

Intended for cron/scheduler once the app is public. Safe to re-run — the batch
build is idempotent and each anchoring step degrades independently.

    cd backend && python anchor_daily.py [YYYY-MM-DD]
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

import base_anchor
import commitments
import db


def main() -> None:
    day = (sys.argv[1] if len(sys.argv) > 1
           else (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat())
    db.init_db()
    built = commitments.build_batch(day)
    print(json.dumps(built, indent=2, default=str))
    if built.get("status") != "built":
        return
    ots = commitments.stamp_ots(day)
    print("ots:", json.dumps(ots))
    base = base_anchor.anchor_root(built["root"])
    db.update_anchor(
        built["id"],
        base_status=base["status"], base_network=base["network"],
        base_chain_id=base["chain_id"], base_tx=base["tx_hash"],
        base_block=base["block"], base_block_time=base.get("block_time"),
        base_error=base["error"],
    )
    print("base:", json.dumps({k: v for k, v in base.items() if k != "error"}))


if __name__ == "__main__":
    main()
