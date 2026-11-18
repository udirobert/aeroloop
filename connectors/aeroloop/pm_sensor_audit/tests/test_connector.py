"""Fixture-based test for the pm-sensor-audit connector: convert only, no network."""
import json

from timenet.types import AnswerTask, ClassificationTask, ForecastingTask

from connectors.aeroloop.pm_sensor_audit.connector import AuditPair, PmSensorAuditConnector


def _pair(hours: int = 96) -> dict:
    """A synthetic pair shaped exactly like a download-stage pair JSON."""
    from datetime import datetime, timedelta, timezone
    t0 = datetime(2025, 10, 31, tzinfo=timezone.utc)
    grid = [(t0 + timedelta(hours=i)).strftime("%Y-%m-%d %H:00:00")
            for i in range(hours)]
    sensor = {h: 8.0 + i * 0.1 for i, h in enumerate(grid)}
    del sensor[grid[5]]  # one reported gap -> a null, never filled
    reference = {h: 6.0 + i * 0.05 for i, h in enumerate(grid)}
    return {
        "uid": "sc:1", "species": "PM10", "sensor_type": "SDS011",
        "reference": "NL00000", "reference_network": "Luchtmeetnet",
        "distance_m": 10.0, "window_start": "2025-10-31",
        "window_end": "2025-11-03", "paired_hours": hours,
        "sensor": sensor, "reference_series": reference,
        "score": {
            "status": "unfit", "n_days": 4, "completeness": 1.0,
            "daily": {"slope": 1.5, "r2": 0.9, "rmse": 9.0, "bias": 2.0},
            "epa_checks": {"completeness_ge_75pct": True, "slope_within_0_65_1_35": False},
            "drift": {"drift_flag": False, "bias_shift": 0.5},
            "standard": "US EPA 2021 PM2.5 sensor performance targets",
        },
    }


def test_convert_builds_records_and_tasks(tmp_path):
    path = tmp_path / "pair.json"
    path.write_text(json.dumps(_pair()))
    dataset = PmSensorAuditConnector().convert([AuditPair(path=path)])
    records = list(dataset.records)
    assert len(records) == 2  # audit-context + forecast-target
    ctx, tgt = records
    sensor_sig, ref_sig = ctx.walk_signals()
    assert len(sensor_sig.to_arrow()) == 96 - 24
    assert sensor_sig.null_count == 1
    assert len(ref_sig.to_arrow()) == 96 - 24
    assert len(next(tgt.walk_signals()).to_arrow()) == 24
    kinds = [type(t) for t in dataset.tasks]
    assert sorted(k.__name__ for k in kinds) == [
        "AnswerTask", "ClassificationTask", "ForecastingTask"]
    cls = next(t for t in dataset.tasks if isinstance(t, ClassificationTask))
    assert cls.targets[0].read() == "unfit"
    fc = next(t for t in dataset.tasks if isinstance(t, ForecastingTask))
    assert fc.targets == (tgt,)
    ans = next(t for t in dataset.tasks if isinstance(t, AnswerTask))
    assert ans.targets[0].read().startswith("Unfit:")
    anns = {a.key for a in ctx.annotations}
    assert {"audit_report", "drift_flag", "epa_slope", "epa_check"} <= anns
