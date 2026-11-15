"""Milestone 2a tests: reference sites, multi-site backfill, trust, sensors,
co-location. No network — all fetches mocked."""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

import colocation
import data_sources as ds
import db
import reference_sites
import trust
from models import GroundReading, Prediction, Strategy
from sensors import breathe_london, sensor_community

UTC = timezone.utc


# ---------------------------------------------------------------------------
# reference_sites
# ---------------------------------------------------------------------------

def _sites():
    return [
        {"code": "KC1", "name": "Kennington", "lat": 51.5, "lon": -0.1,
         "date_closed": None, "species": ["PM10"]},  # PM25 NOT listed
        {"code": "BL0", "name": "Bloomsbury", "lat": 51.52, "lon": -0.13,
         "date_closed": None, "species": ["PM25", "PM10"]},  # listed, empty
        {"code": "TH2", "name": "Tower Hamlets", "lat": 51.53, "lon": -0.05,
         "date_closed": None, "species": ["PM25"]},
        {"code": "XX9", "name": "Closed", "lat": 51.0, "lon": 0.0,
         "date_closed": "2020-01-01", "species": ["PM25"]},  # closed
    ]


def _fake_laqn(species_code_map):
    async def fetch(code, species, start, end):
        key = (code, species)
        n = species_code_map.get(key, 0)
        base = datetime(2026, 11, 1)
        return {
            (base + timedelta(hours=i)).strftime("%Y-%m-%d %H:00:00"): 10.0
            for i in range(n)
        }
    return fetch


def test_discovery_empirical_qualification(temp_db, monkeypatch):
    """Metadata is unreliable both ways: KC1 unlisted-but-full qualifies,
    BL0 listed-but-empty does not."""
    async def sites():
        return _sites()
    monkeypatch.setattr(ds, "fetch_laqn_sites", sites)
    # window 2026-11-01..2026-11-04 = 96 expected hours
    monkeypatch.setattr(ds, "fetch_laqn_species", _fake_laqn({
        ("KC1", "PM25"): 96, ("KC1", "PM10"): 10,
        ("BL0", "PM25"): 0, ("BL0", "PM10"): 0,
        ("TH2", "PM25"): 96, ("TH2", "PM10"): 80,
        ("XX9", "PM25"): 96, ("XX9", "PM10"): 96,  # closed — never probed
    }))

    s = datetime(2026, 11, 1, tzinfo=UTC)
    e = datetime(2026, 11, 4, tzinfo=UTC)
    rows = asyncio.run(reference_sites.discover_async(s, e))

    by = {(r["code"], r["species"]): r for r in rows}
    assert ("XX9", "PM25") not in by  # closed sites aren't probed
    assert by[("KC1", "PM25")]["qualifies"] == 1
    assert by[("KC1", "PM25")]["coverage"] == 1.0
    assert by[("KC1", "PM10")]["qualifies"] == 0
    assert by[("BL0", "PM25")]["qualifies"] == 0  # listed but empty
    assert by[("TH2", "PM25")]["qualifies"] == 1
    assert by[("TH2", "PM10")]["qualifies"] == 1  # 80/96 = 83% ≥ 75%
    assert by[("TH2", "PM10")]["expected_hours"] == 96

    # re-probe upserts (PK code+species), no duplicates
    asyncio.run(reference_sites.discover_async(s, e))
    stored = db.get_reference_sites()
    assert len(stored) == len(by)
    qual = db.get_reference_sites(species="PM25", qualifying=True)
    assert sorted(r["code"] for r in qual) == ["KC1", "TH2"]


# ---------------------------------------------------------------------------
# multi-site backfill
# ---------------------------------------------------------------------------

def test_backfill_site_idempotent_hindcast(temp_db, monkeypatch):
    import backfill_laqn as bl

    base = datetime(2026, 11, 1)

    async def truth(code, start, end):
        return {(base + timedelta(hours=i)).strftime("%Y-%m-%d %H:00:00"): 12.0
                for i in range(24)}

    async def history(url, lat, lon, hourly, start, end):
        times = [base.replace(tzinfo=UTC) + timedelta(hours=i)
                 for i in range(48)]
        idx = {t: i for i, t in enumerate(times)}
        h = {"time": [t.strftime("%Y-%m-%dT%H:00") for t in times]}
        for key in hourly.split(","):
            h[key] = [5.0] * 48
        return idx, h

    monkeypatch.setattr(ds, "fetch_laqn_pm25", truth)
    monkeypatch.setattr(bl, "_fetch_history", history)

    n1 = asyncio.run(bl.backfill_site("laqn:TH2", "TH2", 51.53, -0.05,
                                      "2026-11-01", "2026-11-02",
                                      "LAQN TH2 reference PM2.5 (published)"))
    assert n1 == 24
    n2 = asyncio.run(bl.backfill_site("laqn:TH2", "TH2", 51.53, -0.05,
                                      "2026-11-01", "2026-11-02",
                                      "LAQN TH2 reference PM2.5 (published)"))
    assert n2 == 0  # idempotent

    preds = db.get_predictions("laqn:TH2")
    assert len(preds) == 24
    assert all(p["commit_kind"] == "hindcast" for p in preds)
    readings = db.get_readings("laqn:TH2")
    assert len(readings) == 24
    assert readings[0]["source"] == "LAQN TH2 reference PM2.5 (published)"


# ---------------------------------------------------------------------------
# trust scoring
# ---------------------------------------------------------------------------

def _triples(n_days, fn, hours=24, start=None):
    """Hourly (ts, subject, reference) triples; fn(day, hour) -> (s, r)."""
    start = start or datetime(2026, 1, 1)
    out = []
    for d in range(n_days):
        for h in range(hours):
            s, r = fn(d, h)
            ts = (start + timedelta(days=d, hours=h)).isoformat()
            out.append((ts, s, r))
    return out


def test_daily_aggregation_drops_partial_days():
    # 3 full days + 1 day with only 10h (<18h -> dropped)
    t = _triples(3, lambda d, h: (11.0, 10.0))
    t += _triples(1, lambda d, h: (11.0, 10.0), hours=10,
                  start=datetime(2026, 1, 4))
    daily = trust.daily_means(t)
    assert len(daily) == 3


def test_trust_metrics_hand_computed():
    # 3 days, subject = ref + 2, refs 10/20/30 daily mean
    t = _triples(3, lambda d, h: (12 + 10 * d, 10 + 10 * d))
    r = trust.score_triples(t, min_days=3)
    d = r["daily"]
    assert r["n_days"] == 3
    assert d["slope"] == pytest.approx(1.0)
    assert d["intercept"] == pytest.approx(2.0)
    assert d["r2"] == pytest.approx(1.0)
    assert d["rmse"] == pytest.approx(2.0)
    assert d["bias"] == pytest.approx(2.0)
    assert d["nrmse"] == pytest.approx(0.1)
    assert r["status"] == "fit"
    assert r["meets_epa_targets"] is True
    assert "not certification" in r["standard"]


def test_epa_edge_cases():
    # slope exactly 0.65 and 1.35 pass (inclusive bounds)
    for slope in (0.65, 1.35):
        t = _triples(8, lambda d, h, s=slope: (s * (10 + d), 10 + d))
        r = trust.score_triples(t, min_days=7)
        assert r["epa_checks"]["slope_within_0_65_1_35"] is True
    # intercept exactly ±5 pass
    for b in (-5, 5):
        t = _triples(8, lambda d, h, b=b: ((10 + d) + b, 10 + d))
        r = trust.score_triples(t, min_days=7)
        assert r["epa_checks"]["intercept_within_pm5"] is True
    # RMSE 8 (>7) but NRMSE ~0.27 (<=30%) satisfies the error target
    refs = [10, 20, 30, 40, 50, 60, 30, 25]

    def fn(d, h):
        noise = 8.0 if (d % 2 == 0) else -8.0
        return refs[d] + noise, refs[d]
    r = trust.score_triples(_triples(8, fn), min_days=7)
    assert r["daily"]["rmse"] > 7
    assert r["daily"]["nrmse"] <= 0.30
    assert r["epa_checks"]["rmse_le_7_or_nrmse_le_30pct"] is True


def test_drift_and_statuses():
    # alternating refs keep R² high; bias step +8 in second half flags drift
    # (shift 8 > max(2.0, 0.25 * mean_ref 25) = 6.25)
    def fn(d, h):
        ref = 10.0 if d % 2 == 0 else 40.0
        bias = 0.0 if d < 4 else 8.0
        return ref + bias, ref
    r = trust.score_triples(_triples(8, fn), min_days=7)
    assert r["drift"]["drift_flag"] is True
    assert r["drift"]["bias_shift"] == pytest.approx(8.0)
    assert r["status"] == "drifting"

    # unfit: slope way off
    r2 = trust.score_triples(
        _triples(8, lambda d, h: (2 * (10 + d), 10 + d)), min_days=7)
    assert r2["status"] == "unfit"

    # insufficient evidence
    r3 = trust.score_triples(_triples(3, lambda d, h: (11.0, 10.0)))
    assert r3["status"] == "insufficient_evidence"


def _seed_laqn_site(site="laqn:AA", n_days=12):
    """Hourly predictions+readings; model = actual - 1.5 (v1 predicts model)."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(n_days * 24):
        ts = base + timedelta(hours=i)
        ref = 10.0 + (i % 24) / 24
        db.save_prediction(Prediction(
            station_id=site, timestamp=ts, predicted_pm25=ref - 1.5,
            confidence=0.7, strategy_version="v1-baseline",
            agent_version="t", inputs={"pm25_model": ref - 1.5},
            source_timestamps={}), kind="hindcast")
        db.save_reading(GroundReading(
            station_id=site, timestamp=ts, measured_pm25=ref,
            source="LAQN AA reference PM2.5 (published)"))


def test_trust_report_cams_raw_and_incumbent(temp_db):
    """cams_raw scores the model input over the full window; incumbent scores
    the incumbent strategy on the chronological holdout only."""
    db.save_strategy(Strategy(version="v1-baseline", description="x",
                              params={}, created_at=datetime.now(UTC)))
    _seed_laqn_site()
    rep = trust.trust_report("cams_raw")
    assert "laqn:AA" in rep["sites"]
    raw_days = rep["sites"]["laqn:AA"]["n_days"]
    assert raw_days == 12

    inc = trust.trust_report("incumbent")
    assert inc["incumbent_version"] == "v1-baseline"
    assert inc["window"] == "holdout"
    inc_days = inc["sites"]["laqn:AA"]["n_days"]
    # holdout = last ~1/3 of pairs chronologically
    assert inc_days < raw_days
    assert inc_days >= 3


# ---------------------------------------------------------------------------
# sensors
# ---------------------------------------------------------------------------

BL_SENSOR = {"SiteCode": "BL0057", "SiteName": "X", "DeviceCode": "13546",
             "InstallationCode": "120004", "Latitude": "51.4856300",
             "Longitude": "-0.1191570", "Borough": "Lambeth",
             "SiteClassification": "Urban Background",
             "SensorHeightAboveGround": 2.9, "DistanceToKerb": 14.6,
             "SponsorName": "GLA", "SiteLocationType": "School",
             "StartDate": "2025-04-09T00:00:00Z", "EndDate": None}

BL_ROW = {"Species": "PM25", "Source": "Measurement", "Units": "ug.m-3",
          "SiteCode": "BL0086", "DateTime": "2025-04-01T00:00:00Z",
          "Duration": "PT1H", "ScaledValue": 5.55, "RatificationStatus": "P",
          "SensorContract": "Vodafone"}


def test_breathe_london_parsing_and_not_configured(monkeypatch):
    monkeypatch.delenv("BREATHE_LONDON_API_KEY", raising=False)
    assert breathe_london.list_sensors()["status"] == "not_configured"
    assert breathe_london.sensor_data("X", "a", "b")["status"] == "not_configured"

    monkeypatch.setenv("BREATHE_LONDON_API_KEY", "test-key")

    def handler(req):
        if "ListSensors" in req.url.path:
            return httpx.Response(200, json=[BL_SENSOR])
        if "SensorData" in req.url.path:
            return httpx.Response(200, json=[BL_ROW])
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ls = breathe_london.list_sensors(client=client)
    assert ls["status"] == "ok"
    s = ls["sensors"][0]
    assert s["uid"] == "bl:BL0057"
    assert s["lat"] == pytest.approx(51.48563)
    assert s["meta"]["Borough"] == "Lambeth"
    assert "Open Government License" in ls["attribution"]

    sd = breathe_london.sensor_data("BL0086", "2025-04-01", "2025-04-02",
                                    client=client)
    r = sd["readings"][0]
    assert r["uid"] == "bl:BL0086"
    assert r["value"] == 5.55
    assert r["flags"]["ratification_status"] == "P"
    assert r["flags"]["sensor_contract"] == "Vodafone"


def test_sensor_community_parsing():
    rows = [
        {"sensor": {"id": 77668, "sensor_type": {"name": "SDS011"}},
         "location": {"latitude": "51.5", "longitude": "-0.1", "indoor": 0},
         "sensordatavalues": [{"value_type": "P1", "value": "9"},
                              {"value_type": "P2", "value": "5"}]},
        {"sensor": {"id": 999, "sensor_type": {"name": "BME280"}},
         "location": {"latitude": "51.5", "longitude": "-0.1", "indoor": 0},
         "sensordatavalues": [{"value_type": "temperature", "value": "12"}]},
        {"sensor": {"id": 777, "sensor_type": {"name": "SDS011"}},
         "location": {"latitude": "51.5", "longitude": "-0.1", "indoor": 1},
         "sensordatavalues": [{"value_type": "P2", "value": "5"}]},
    ]

    def handler(req):
        assert req.headers.get("user-agent")
        return httpx.Response(200, json=rows)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    res = sensor_community.list_pm_sensors(51.5, -0.1, 5, client=client)
    uids = {s["uid"] for s in res["sensors"]}
    assert uids == {"sc:77668", "sc:777"}  # non-PM sensor excluded
    indoor = {s["uid"]: s["indoor"] for s in res["sensors"]}
    assert indoor["sc:777"] == 1
    assert indoor["sc:77668"] == 0


# ---------------------------------------------------------------------------
# colocation
# ---------------------------------------------------------------------------

def test_colocation_tiers_and_attribution(temp_db):
    db.upsert_reference_site({
        "code": "TH2", "species": "PM25", "name": "T", "lat": 51.53,
        "lon": -0.05, "qualifies": 1})
    now = "2026-01-01T00:00:00Z"
    db.upsert_sensor({"uid": "sc:1", "source": "sensor_community",
                      "lat": 51.5305, "lon": -0.0505, "indoor": 0,
                      "meta": {}, "listed_at": now})  # ~70m away
    db.upsert_sensor({"uid": "sc:2", "source": "sensor_community",
                      "lat": 52.0, "lon": -0.2, "indoor": 0,
                      "meta": {}, "listed_at": now})  # far
    db.upsert_sensor({"uid": "sc:3", "source": "sensor_community",
                      "lat": 51.5305, "lon": -0.0505, "indoor": 1,
                      "meta": {}, "listed_at": now})  # indoor
    db.upsert_sensor({"uid": "bl:B1", "source": "breathe_london",
                      "lat": 51.5305, "lon": -0.0505, "indoor": 0,
                      "meta": {}, "listed_at": now})
    rep = colocation.colocation_report("PM25")
    t = rep["tiers"]
    assert t["verified_candidate"] == 2
    assert t["no_reference_nearby"] == 1
    assert t["excluded_indoor"] == 1
    near = [r for r in rep["rows"] if r["uid"] == "sc:1"][0]
    assert near["nearest_reference"] == "TH2"
    assert near["distance_m"] < 200
    assert "attribution" in rep  # bl: row present -> OGL attribution


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

def test_endpoints(temp_db, monkeypatch):
    from fastapi.testclient import TestClient
    import main

    db.upsert_reference_site({
        "code": "KC1", "species": "PM25", "name": "K", "lat": 51.5,
        "lon": -0.1, "qualifies": 1})
    _seed_laqn_site()
    db.upsert_sensor({"uid": "sc:1", "source": "sensor_community",
                      "lat": 51.5, "lon": -0.1, "indoor": 0,
                      "meta": {}, "listed_at": "x"})

    with TestClient(main.app) as c:
        r = c.get("/reference-sites?species=PM25&qualifying=true")
        assert r.status_code == 200
        assert [x["code"] for x in r.json()] == ["KC1"]

        r = c.get("/trust?subject=cams_raw")
        assert r.status_code == 200
        assert r.json()["sites"]["laqn:AA"]["status"] in (
            "fit", "drifting", "unfit", "insufficient_evidence")
        assert "not certification" in r.json()["standard"]

        r = c.get("/trust?subject=bogus")
        assert r.status_code == 400

        r = c.get("/colocation?species=PM25")
        assert r.status_code == 200
        assert r.json()["tiers"]["verified_candidate"] == 1
