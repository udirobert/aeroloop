"""Connector for ``aeroloop/pm-sensor-audit``.

Raw source: AeroLoop's sensor-vs-reference audit corpus — hourly PM series from
co-located low-cost sensors (sensor.community archive, Breathe London) and
official reference monitors (LAQN, RIVM Luchtmeetnet), plus the audit verdict
the trust engine scored over each paired window.

``download`` materializes one pair JSON per ``(sensor_uid, species, window)``
into ``cache_dir``. It reads audit rows from the AeroLoop SQLite snapshot
(``AEROLOOP_AUDIT_DB``), pulls the sensor series from the same snapshot (or the
sensor's own archive when the snapshot is thin), and always fetches the
reference series live, since the snapshot stores verdicts, not reference hours.
``AEROLOOP_PAIRS_DIR`` points at pre-collected pair JSONs for fully offline
builds.

``convert`` emits two records per pair — an audit-context record over the first
``window - AEROLOOP_FORECAST_HOURS`` (both signals, verdict annotations,
classification + answer tasks) and a forecast-target record holding the final
``AEROLOOP_FORECAST_HOURS`` of the reference signal (the ``ForecastingTask``
answer). The verdict labels describe the full audit window; the context input
stops before the forecast horizon, so the classifier answers from history only.

Configuration comes from the environment (connectors take no arguments):

- ``AEROLOOP_AUDIT_DB`` — SQLite audit snapshot (default ``<repo>/data/aeroloop.db``).
- ``AEROLOOP_SPECIES`` — restrict to ``PM25`` or ``PM10`` (default: all).
- ``AEROLOOP_MAX_PAIRS`` — cap pairs for a quick build.
- ``AEROLOOP_FORECAST_HOURS`` — forecast horizon, default ``24``.
- ``AEROLOOP_PAIRS_DIR`` — read pair JSONs from a directory instead of the
  audit DB + live fetches (offline rebuilds).
- ``AEROLOOP_BACKEND_DIR`` — AeroLoop backend path for the fetchers
  (default ``<repo>/backend``).
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

from timenet.connectors import BaseConnector
from timenet.dataset import Record, Signal, Source, TimeFDataset
from timenet.dataset.axis import RegularAxis
from timenet.types import (
    Annotation,
    AnswerTask,
    ClassificationTask,
    ForecastingTask,
    Label,
    LabelSet,
    MissingReason,
    MissingValues,
    TimeSeriesSpec,
    ureg,
)
from timenet.types.clock import TimeOrigin

_REPO = Path(__file__).resolve().parents[3]
REFERENCE_SPACING_S = 1.5  # Luchtmeetnet fair-use, matches backend/sensor_audit.py
HOUR_US = Fraction(3_600_000_000)  # 3600 s in microseconds
TS_FORMAT = "%Y-%m-%d %H:00:00"

SPECIES_DISPLAY = {"PM25": "PM2.5", "PM10": "PM10"}

TRUST_STATUS = LabelSet(
    name="sensor_trust_status",
    labels=(
        Label(name="fit", description="Sensor tracks its reference within indicative EPA 24-h targets."),
        Label(name="drifting", description="Sensor meets the letter of the targets but its bias is shifting."),
        Label(name="unfit", description="Sensor fails one or more indicative EPA performance checks."),
        Label(name="insufficient_evidence", description="Too few paired days to score."),
    ),
)

AUDIT_PROMPT = (
    "This record pairs a low-cost PM sensor with a co-located official "
    "reference monitor over one audit window. Is the sensor fit, drifting, "
    "or unfit, and why?"
)
FORECAST_PROMPT = (
    "Given this co-located pair's recent history, forecast the reference "
    "monitor's hourly PM for the next {hours} hours."
)


@dataclass(frozen=True)
class AuditPair:
    """One materialized pair file from :meth:`PmSensorAuditConnector.download`."""

    path: Path


def _env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    return v if v else default


def _db_path() -> Path:
    return Path(_env("AEROLOOP_AUDIT_DB", str(_REPO / "data" / "aeroloop.db")))


def _hours(start: datetime, end_exclusive: datetime) -> list[str]:
    """Hour keys ``TS_FORMAT`` over ``[start, end_exclusive)``."""
    n = int((end_exclusive - start).total_seconds() // 3600)
    return [(start + timedelta(hours=i)).strftime(TS_FORMAT) for i in range(n)]


def _spec(species: str, role: str) -> TimeSeriesSpec:
    return TimeSeriesSpec(
        spec_type=f"{species.lower()}_{role}",
        name=f"{SPECIES_DISPLAY.get(species, species)} {role}",
        unit_value=ureg.microgram / ureg.meter**3,
        missing=MissingValues(
            reason=MissingReason.SENSOR_GAP,
            description="No valid hourly mean was reported for this timestep.",
        ),
    )


def _signal(values: list[float | None], *, spec: TimeSeriesSpec, name: str) -> Signal:
    return Signal.from_values(
        values, spec=spec, name=name, time_axis=RegularAxis(period_us=HOUR_US)
    )


def _verdict(score: dict[str, Any]) -> str:
    """One-line verdict from the stored audit score."""
    status = score.get("status", "insufficient_evidence")
    daily = score.get("daily") or {}
    drift = score.get("drift") or {}
    if status == "insufficient_evidence":
        return ("Insufficient evidence: too few paired days between the sensor "
                "and its reference to score.")
    parts = [f"{status.capitalize()}:"]
    if daily.get("r2") is not None:
        parts.append(f"r² {daily['r2']:.2f},")
    if daily.get("slope") is not None:
        parts.append(f"slope {daily['slope']:.2f} vs EPA 0.65–1.35,")
    if daily.get("bias") is not None:
        parts.append(f"bias {daily['bias']:+.1f} µg/m³,")
    if daily.get("rmse") is not None:
        parts.append(f"RMSE {daily['rmse']:.1f} µg/m³")
    if drift.get("drift_flag"):
        parts.append("— drift flag set on the second half of the window.")
    return " ".join(parts)


def _reasoning(score: dict[str, Any]) -> str:
    """The evidence paragraph behind the verdict."""
    checks = (score.get("epa_checks") or {})
    failed = [k for k, v in checks.items() if v is False]
    drift = score.get("drift") or {}
    out = [f"Indicative EPA 24-h checks: {len(checks) - len(failed)}/{len(checks)} passed."]
    if failed:
        out.append("Failed: " + ", ".join(failed) + ".")
    if drift:
        out.append(drift.get("note") or
                   f"Bias shift between halves: {drift.get('bias_shift', 0):+.1f} µg/m³.")
    out.append(score.get("standard") or "")
    return " ".join(p for p in out if p)


class PmSensorAuditConnector(BaseConnector[AuditPair]):
    """Connector for the AeroLoop co-located PM audit dataset."""

    # -- download ---------------------------------------------------------

    async def download_async(self, cache_dir: Path) -> list[AuditPair]:
        """Materialize pair JSONs and return one ref per pair.

        Reads audit rows from the AeroLoop snapshot, fills the sensor series
        from the snapshot (or the sensor archive), and always fetches the
        reference series live. Existing pair files are reused, keeping the
        stage idempotent for a given ``cache_dir``.

        Args:
            cache_dir: Directory for the materialized pair JSONs.

        Returns:
            One :class:`AuditPair` per pair.
        """
        pairs_dir = _env("AEROLOOP_PAIRS_DIR")
        if pairs_dir:
            return [AuditPair(path=p) for p in sorted(Path(pairs_dir).glob("*.json"))]
        cache_dir.mkdir(parents=True, exist_ok=True)
        audits = self._audit_rows()
        refs: list[AuditPair] = []
        todo: list[tuple[dict[str, Any], Path]] = []
        for a in audits:
            name = f"pair_{a['uid']}_{a['species']}_{a['window_start']}_{a['window_end']}"
            name = name.replace(":", "-")
            path = cache_dir / f"{name}.json"
            if path.is_file():
                refs.append(AuditPair(path=path))
            else:
                todo.append((a, path))
        if todo:
            await self._collect(todo)
            refs.extend(AuditPair(path=p) for _, p in todo if p.is_file())
        return refs

    def _audit_rows(self) -> list[dict[str, Any]]:
        """Latest audit per (uid, species, window) from the snapshot."""
        con = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            q = """SELECT a.*, r.network AS reference_network FROM sensor_audits a
                   LEFT JOIN reference_sites r ON r.code = a.reference AND r.species = a.species
                   WHERE (a.uid, a.species, a.window_start, a.window_end, a.audited_at) IN
                         (SELECT uid, species, window_start, window_end, MAX(audited_at)
                          FROM sensor_audits GROUP BY uid, species, window_start, window_end)"""
            args: list[Any] = []
            if _env("AEROLOOP_SPECIES"):
                q += " AND a.species = ?"
                args.append(_env("AEROLOOP_SPECIES"))
            rows = [dict(r) for r in con.execute(q, args)]
            # sensor series for the same windows, keyed (uid, species)
            readings: dict[tuple[str, str], dict[str, float]] = {}
            for r in con.execute("SELECT uid, timestamp, species, value FROM sensor_readings"):
                readings.setdefault((r["uid"], r["species"]), {})[r["timestamp"]] = r["value"]
        finally:
            con.close()
        limit = int(_env("AEROLOOP_MAX_PAIRS") or 0) or None
        out = []
        for a in rows[:limit]:
            a["sensor_series"] = readings.get((a["uid"], a["species"]), {})
            out.append(a)
        return out

    async def _collect(self, todo: list[tuple[dict[str, Any], Path]]) -> None:
        """Fetch missing pair inputs and write one JSON per audit."""
        backend = Path(_env("AEROLOOP_BACKEND_DIR", str(_REPO / "backend")))
        if str(backend) not in sys.path:
            sys.path.insert(0, str(backend))
        from sensors import luchtmeetnet as lm  # noqa: PLC0415
        from sensors import sensor_community as sc  # noqa: PLC0415
        import data_sources  # noqa: PLC0415

        lm_client = lm._client()
        sc_client = sc._client()
        try:
            for a, path in todo:
                start = datetime.strptime(a["window_start"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                end = datetime.strptime(a["window_end"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                end_ex = end + timedelta(days=1)
                sensor_series = a.get("sensor_series") or {}
                if not sensor_series:
                    sensor_series = await self._sensor_series(a, start, end, sc_client)
                network = a.get("reference_network") or (
                    "Luchtmeetnet" if str(a["reference"]).startswith("NL") else "LAQN")
                if network == "Luchtmeetnet":
                    ref = await lm.fetch_measurements(
                        a["reference"], a["species"], start, end_ex, client=lm_client)
                else:
                    ref = await data_sources.fetch_laqn_species(
                        a["reference"], a["species"], start, end_ex)
                payload = {
                    "uid": a["uid"], "species": a["species"],
                    "sensor_type": a.get("sensor_type"),
                    "reference": a["reference"], "reference_network": network,
                    "distance_m": a.get("distance_m"),
                    "window_start": a["window_start"], "window_end": a["window_end"],
                    "paired_hours": a.get("paired_hours"),
                    "sensor": sensor_series, "reference_series": ref,
                    "score": json.loads(a["score"]) if isinstance(a["score"], str) else a["score"],
                }
                path.write_text(json.dumps(payload))
                await asyncio.sleep(REFERENCE_SPACING_S)
        finally:
            await lm_client.aclose()
            sc_client.close()

    async def _sensor_series(self, a: dict[str, Any], start: datetime,
                             end: datetime, sc_client: Any) -> dict[str, float]:
        """Fetch a sensor's hourly means when the snapshot has none."""
        if not str(a["uid"]).startswith("sc:"):
            return {}
        from sensors import sensor_community as sc  # noqa: PLC0415

        rows = await asyncio.to_thread(
            sc.fetch_sensor_history, int(a["uid"].split(":", 1)[1]),
            (a.get("sensor_type") or "sds011").lower(), start, end, sc_client)
        return {r["timestamp"]: r["value"] for r in rows if r["species"] == a["species"]}

    # -- convert ----------------------------------------------------------

    def convert(self, raw_refs: list[AuditPair]) -> TimeFDataset:
        """Build two records and three tasks per audit pair.

        Args:
            raw_refs: Pair files from :meth:`download_async`.

        Returns:
            The populated :class:`~timenet.dataset.TimeFDataset`.
        """
        horizon = int(_env("AEROLOOP_FORECAST_HOURS", "24"))
        dataset = TimeFDataset(metadata=self.metadata())
        for ref in raw_refs:
            pair = json.loads(ref.path.read_text())
            self._emit_pair(dataset, pair, horizon)
        return dataset

    def _emit_pair(self, dataset: TimeFDataset, pair: dict[str, Any], horizon: int) -> None:
        """One audit pair -> context record, forecast-target record, three tasks."""
        species = pair["species"]
        ws = datetime.strptime(pair["window_start"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        we = datetime.strptime(pair["window_end"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_ex = we + timedelta(days=1)
        grid = _hours(ws, end_ex)
        sensor_all = [pair["sensor"].get(h) for h in grid]
        ref_all = [pair["reference_series"].get(h) for h in grid]
        split = max(1, len(grid) - horizon)

        sensor_spec = _spec(species, "lowcost_sensor")
        ref_spec = _spec(species, "reference")
        sensor_sig = _signal(sensor_all[:split], spec=sensor_spec, name=f"{species.lower()}_sensor")
        ref_sig = _signal(ref_all[:split], spec=ref_spec, name=f"{species.lower()}_reference")
        site = Source(
            name=f"colocated-site/{pair['uid']}:{pair['reference']}",
            sources=(
                Source(name=f"lowcost-sensor/{pair['uid']}", signals=(sensor_sig,)),
                Source(name=f"reference/{pair['reference']}", signals=(ref_sig,)),
            ),
        )
        ctx = dataset.add_record(record=Record(
            sources=(site,),
            start_time=TimeOrigin(timestamp=ws),
            metadata={
                "sensor_uid": pair["uid"], "species": species,
                "reference": pair["reference"],
                "reference_network": pair.get("reference_network"),
                "window_start": pair["window_start"], "window_end": pair["window_end"],
                "role": "audit-context",
            },
        ))

        score = pair.get("score") or {}
        ctx.annotate(Annotation(
            key="audit_report", value=score.get("status", "insufficient_evidence"),
            description="AeroLoop audit verdict (indicative EPA 24-h checks + drift heuristic)",
            metadata=score))
        ctx.annotate(Annotation(key="sensor_type", value=pair.get("sensor_type") or "unknown"))
        ctx.annotate(Annotation(
            key="colocation_distance", value=pair.get("distance_m"), unit="meter",
            description="Distance between the low-cost sensor and its reference monitor"))
        for key in ("slope", "r2", "rmse", "bias", "nrmse", "mae"):
            v = (score.get("daily") or {}).get(key)
            if v is not None:
                ctx.annotate(Annotation(key=f"epa_{key}", value=v))
        for name, ok in (score.get("epa_checks") or {}).items():
            ctx.annotate(Annotation(key="epa_check", value=name, metadata={"passed": ok}))
        drift = score.get("drift") or {}
        if drift.get("drift_flag") is not None:
            ctx.annotate(Annotation(key="drift_flag", value=bool(drift["drift_flag"]),
                                    description=drift.get("note")))

        status = score.get("status", "insufficient_evidence")
        dataset.add_task(task=ClassificationTask(
            inputs=(ctx,), prompt=AUDIT_PROMPT, label_set=TRUST_STATUS,
            targets=(status,)))
        dataset.add_task(task=AnswerTask(
            inputs=(ctx,), prompt=AUDIT_PROMPT,
            targets=(_verdict(score),), rationale=_reasoning(score)))

        if horizon >= len(grid):
            return
        tgt_sig = _signal(ref_all[split:], spec=_spec(species, "reference"),
                          name=f"{species.lower()}_reference")
        tgt = dataset.add_record(record=Record(
            sources=(Source(
                name=f"reference/{pair['reference']}",
                signals=(tgt_sig,)),),
            start_time=TimeOrigin(timestamp=ws + timedelta(hours=split)),
            metadata={
                "sensor_uid": pair["uid"], "species": species,
                "reference": pair["reference"],
                "window_start": (ws + timedelta(hours=split)).date().isoformat(),
                "window_end": pair["window_end"],
                "role": "forecast-target",
            },
        ))
        dataset.add_task(task=ForecastingTask(
            inputs=(ctx,), targets=(tgt,),
            prompt=FORECAST_PROMPT.format(hours=horizon)))


CONNECTOR = PmSensorAuditConnector
