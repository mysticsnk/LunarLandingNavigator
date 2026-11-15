from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from test_stage1_jobs import check_schema

from app.astronomy.horizons import EphemerisObservation
from app.core.problems import APIProblem
from app.requests import TimelineRequest
from app.results import TimelineResult
from app.storage import request_key
from app.worker import execute_timeline, run_once

TIMELINE_REQUEST = {
    "site": {"latitude": -89.44, "longitude": 222.1},
    "start_time": "2027-07-15T12:00:00Z",
    "duration_days": 14,
    "step_minutes": 120,
    "horizon_mode": "geometric",
    "observer_height_m": 2,
    "visibility_margin_deg": 0,
}


class ControlledSeriesProvider:
    """Test-only provider with a deterministic series for timeline integration tests."""

    def __init__(self):
        self.calls = []

    def query_body_series(
        self,
        *,
        target,
        latitude,
        longitude,
        altitude_m,
        start_time,
        stop_time,
        step_minutes,
    ):
        start = datetime.fromisoformat(start_time) if isinstance(start_time, str) else start_time
        stop = datetime.fromisoformat(stop_time) if isinstance(stop_time, str) else stop_time
        step = timedelta(minutes=step_minutes)
        self.calls.append(target)
        observations = []
        index = 0
        while start + index * step < stop:
            instant = start + index * step
            elevation = (10.0, -10.0, -10.0, 10.0)[index % 4] if target == "Sun" else 10.0
            observations.append(
                EphemerisObservation(
                    target=target,
                    timestamp=instant.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    azimuth_deg=180.0 if target == "Sun" else 90.0,
                    elevation_deg=elevation,
                    solar_presence=None,
                    interfering_marker=None,
                    source_url=f"https://ssd.jpl.nasa.gov/api/horizons.api?COMMAND={target}",
                    retrieval_time="2026-11-14T12:00:00Z",
                    provider_name="Controlled Horizons test provider",
                    ephemeris_source="fixture-DE441",
                    request_params={"COMMAND": target},
                )
            )
            index += 1
        return observations


def test_timeline_request_rejects_invalid_limits_and_time_boundaries():
    valid = dict(TIMELINE_REQUEST)
    TimelineRequest.model_validate(valid)

    for changes in (
        {"duration_days": 0},
        {"duration_days": 31},
        {"duration_days": 1.5},
        {"step_minutes": 45},
        {"unexpected": True},
        {"start_time": "2027-07-15T12:00:00"},
        {"start_time": "2027-07-15T12:00:00.000001Z"},
        {"start_time": "1999-12-31T23:59:59Z"},
        {"start_time": "2050-01-01T00:00:00Z"},
        {"start_time": "2049-12-31T12:00:00Z"},
        {"site": {"site_id": "site", "latitude": 0, "longitude": 0}},
    ):
        with pytest.raises(ValueError):
            TimelineRequest.model_validate({**valid, **changes})

    boundary = {**valid, "start_time": "2049-12-31T00:00:00Z", "duration_days": 1}
    assert TimelineRequest.model_validate(boundary).start_time == datetime(2049, 12, 31, tzinfo=UTC)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("start_time", "2027-07-16T12:00:00Z"),
        ("duration_days", 13),
        ("step_minutes", 60),
    ],
)
def test_timeline_cache_identity_includes_period_and_sampling(field, value):
    normalized = {
        "kind": "timeline",
        "site": {
            "latitude": -89.44,
            "longitude": -137.9,
            "surface_elevation_m": 0.0,
        },
        "start_time": TIMELINE_REQUEST["start_time"],
        "duration_days": TIMELINE_REQUEST["duration_days"],
        "step_minutes": TIMELINE_REQUEST["step_minutes"],
        "observer_height_m": 2.0,
        "visibility_margin_deg": 0.0,
        "horizon_mode": "geometric",
        "model_version": "geometric-timeline-v1",
    }
    changed = deepcopy(normalized)
    changed[field] = value
    assert request_key(normalized) != request_key(changed)


def test_worker_rejects_service_result_for_a_different_period(monkeypatch):
    normalized = {
        "site": {"latitude": -89.44, "longitude": -137.9},
        "start_time": "2027-07-15T12:00:00Z",
        "end_time": "2027-07-29T12:00:00Z",
        "duration_days": 14,
        "step_minutes": 120,
        "horizon_mode": "geometric",
        "observer_height_m": 2.0,
        "visibility_margin_deg": 0.0,
        "model_version": "geometric-timeline-v1",
    }
    monkeypatch.setattr(
        "app.worker.calculate_timeline",
        lambda **_: SimpleNamespace(
            start_time="2027-07-16T12:00:00Z",
            end_time=normalized["end_time"],
            step_minutes=normalized["step_minutes"],
        ),
    )
    with pytest.raises(APIProblem, match="changed the requested timeline"):
        execute_timeline(normalized, provider=ControlledSeriesProvider())


def test_timeline_http_job_lifecycle_windows_and_cached_result(stage_client, stage_repo):
    provider = ControlledSeriesProvider()
    accepted = stage_client.post("/api/v1/ephemeris/timeline", json=TIMELINE_REQUEST)
    assert accepted.status_code == 202
    check_schema("JobAccepted", accepted.json())
    assert accepted.json()["kind"] == "timeline"
    assert stage_client.get(accepted.json()["result_url"]).status_code == 409

    job = stage_repo.job(accepted.json()["job_id"])
    assert job["kind"] == "timeline"
    assert job["normalized"]["site"]["longitude"] == -137.9
    assert job["normalized"]["start_time"] == TIMELINE_REQUEST["start_time"]
    assert job["normalized"]["end_time"] == "2027-07-29T12:00:00Z"

    def executor(normalized):
        return execute_timeline(normalized, provider=provider)

    assert run_once(stage_repo, executor=executor)
    status = stage_client.get(accepted.json()["status_url"]).json()
    response = stage_client.get(accepted.json()["result_url"])
    assert status["status"] == "succeeded", status
    assert response.status_code == 200
    check_schema("TimelineResult", response.json())
    result = TimelineResult.model_validate(response.json())
    assert result.total_samples == len(result.points) == 168
    assert result.points[0].timestamp == "2027-07-15T12:00:00Z"
    assert result.points[-1].timestamp == "2027-07-29T10:00:00Z"
    assert result.end_time.isoformat().replace("+00:00", "Z") == "2027-07-29T12:00:00Z"
    assert result.earth_visibility_windows[0].end_time == result.end_time
    assert result.summary.next_earthset_at is None
    assert result.summary.next_sunset_at is not None
    assert provider.calls == ["Sun", "Earth"]

    cached_acceptance = stage_client.post("/api/v1/ephemeris/timeline", json=TIMELINE_REQUEST)
    assert cached_acceptance.status_code == 202
    assert run_once(stage_repo, executor=lambda _: pytest.fail("Cache hit must not call provider"))
    cached = stage_client.get(cached_acceptance.json()["result_url"]).json()
    check_schema("TimelineResult", cached)
    assert cached["meta"]["data_status"] == "cached"
    assert cached["meta"]["generated_at"] == response.json()["meta"]["generated_at"]
    assert [source["fetched_at"] for source in cached["meta"]["sources"]] == [
        source["fetched_at"] for source in response.json()["meta"]["sources"]
    ]


def test_timeline_catalog_site_and_terrain_behavior(stage_client, stage_repo):
    request = {**TIMELINE_REQUEST, "site": {"site_id": "test-artemis"}}
    accepted = stage_client.post("/api/v1/ephemeris/timeline", json=request)
    assert accepted.status_code == 202
    assert stage_repo.job(accepted.json()["job_id"])["normalized"]["site"]["site_id"] == (
        "test-artemis"
    )

    terrain = stage_client.post(
        "/api/v1/ephemeris/timeline", json={**request, "horizon_mode": "terrain"}
    )
    assert terrain.status_code == 422
    assert terrain.json()["error"]["code"] == "TERRAIN_UNAVAILABLE"
    check_schema("ErrorEnvelope", terrain.json())
