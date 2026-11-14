"""Stage 2 End-to-End Integration Tests for the Lunar Observation Workflow.

Verifies the complete real observation workflow:
  site selection -> UTC timestamp -> observation job -> Horizons ->
  stored result -> numerical UI contract -> map & local 3D scene compatibility.

Includes:
- Deterministic end-to-end tests based on Stage 0 reference fixtures.
- Custom coordinate normalization and visibility margin enforcement.
- Durable job state progression (queued -> running -> succeeded).
- Result caching and idempotency (fresh vs cached).
- Local ENU to Three.js scene vector mapping (x=east, y=up, z=-north).
- Opt-in live verification against the upstream JPL Horizons API.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import httpx
import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

from app.astronomy import (
    HorizonsParseError,
    HorizonsProvider,
    HorizonsProviderError,
    HorizonsTransportError,
    calculate_geometric_observation,
)
from app.worker import execute_observation, run_once

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "contracts" / "openapi.v1.yaml"
FIXTURES_DIR = ROOT / "contracts" / "reference" / "horizons"
OPENAPI_SPEC = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def load_fixture(filename: str) -> dict:
    fixture_path = FIXTURES_DIR / filename
    assert fixture_path.exists(), f"Fixture file not found: {fixture_path}"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def validate_schema(name: str, instance: dict) -> None:
    schema = {
        "$ref": f"#/components/schemas/{name}",
        "components": OPENAPI_SPEC["components"],
    }
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(instance)


def make_mock_provider(sun_fixture_name: str, earth_fixture_name: str) -> HorizonsProvider:
    sun_raw = load_fixture(sun_fixture_name)["raw_response"]
    earth_raw = load_fixture(earth_fixture_name)["raw_response"]

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "COMMAND=%2710%27" in url_str or "COMMAND='10'" in url_str:
            return httpx.Response(200, json=sun_raw)
        elif "COMMAND=%27399%27" in url_str or "COMMAND='399'" in url_str:
            return httpx.Response(200, json=earth_raw)
        return httpx.Response(400, json={"error": f"Unexpected command in URL: {url_str}"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return HorizonsProvider(client=client)


# --- Deterministic Stage 2 Workflow Tests ---


def test_complete_observation_workflow_catalog_site(stage_client, stage_repo):
    """Verify complete workflow for a catalog site from selection to stored result."""
    # 1. Site selection: query catalog
    sites_res = stage_client.get("/api/v1/sites?category=artemis")
    assert sites_res.status_code == 200
    catalog_sites = sites_res.json()["items"]
    assert len(catalog_sites) >= 1
    selected_site = catalog_sites[0]
    site_id = selected_site["id"]

    # 2. UTC timestamp and observation request
    target_time = "2027-07-15T12:00:00Z"
    request_payload = {
        "site": {"site_id": site_id},
        "target_time": target_time,
        "observer_height_m": 2.0,
        "visibility_margin_deg": 0.0,
        "horizon_mode": "geometric",
    }

    # 3. Observation job submission -> HTTP 202
    submit_res = stage_client.post("/api/v1/ephemeris/now", json=request_payload)
    assert submit_res.status_code == 202
    job_accepted = submit_res.json()
    validate_schema("JobAccepted", job_accepted)
    assert job_accepted["status"] == "queued"
    status_url = job_accepted["status_url"]
    result_url = job_accepted["result_url"]

    # Before execution, result read returns 409 JOB_NOT_READY
    pending_res = stage_client.get(result_url)
    assert pending_res.status_code == 409
    assert pending_res.json()["error"]["code"] == "JOB_NOT_READY"

    # 4. Horizons execution via worker
    mock_provider = make_mock_provider("shackleton-sun.json", "shackleton-earth.json")

    def execute_with_mock_horizons(normalized):
        point = calculate_geometric_observation(
            latitude=normalized["site"]["latitude"],
            longitude=normalized["site"]["longitude"],
            target_time=normalized["target_time"],
            observer_height_m=normalized["observer_height_m"],
            visibility_margin_deg=normalized["visibility_margin_deg"],
            provider=mock_provider,
        )
        return {
            "site": normalized["site"],
            "point": point.model_dump(),
            "meta": {
                "model_version": "geometric-now-v1",
                "generated_at": "2026-11-14T12:00:00Z",
                "data_status": "fresh",
                "horizon_mode": "geometric",
                "time_resolution_minutes": None,
                "terrain_dataset_id": None,
                "sources": [s.to_contract_source() for s in point.sources],
            },
        }

    worked = run_once(stage_repo, executor=execute_with_mock_horizons)
    assert worked is True

    # 5. Stored job state verification
    status_res = stage_client.get(status_url)
    assert status_res.status_code == 200
    status_body = status_res.json()
    validate_schema("Job", status_body)
    assert status_body["status"] == "succeeded"
    assert status_body["finished_at"] is not None

    # 6. Numerical UI contract verification
    result_res = stage_client.get(result_url)
    assert result_res.status_code == 200
    result_body = result_res.json()
    validate_schema("NowResult", result_body)

    # Validate site coordinates and normalization
    assert result_body["site"]["latitude"] == selected_site["latitude"]
    assert result_body["site"]["longitude"] == selected_site["longitude"]
    assert result_body["site"]["surface_elevation_m"] == 0.0
    assert result_body["site"]["observer_height_m"] == 2.0

    # Validate observation values
    point = result_body["point"]
    assert point["timestamp"] == target_time
    # Sun values from Stage 0 Shackleton fixture
    assert point["sun"]["azimuth_deg"] == pytest.approx(177.278712, abs=1e-5)
    assert point["sun"]["elevation_deg"] == pytest.approx(-1.088272, abs=1e-5)
    assert point["sun"]["horizon_elevation_deg"] == 0.0
    assert point["sun"]["visible"] is False
    # Earth values from Stage 0 Shackleton fixture
    assert point["earth"]["azimuth_deg"] == pytest.approx(142.714718, abs=1e-5)
    assert point["earth"]["elevation_deg"] == pytest.approx(-6.178829, abs=1e-5)
    assert point["earth"]["horizon_elevation_deg"] == 0.0
    assert point["earth"]["visible"] is False
    assert point["is_golden_window"] is False

    # 7. Map and 3D scene compatibility checks
    # DirectionENU unit vector invariant: norm == 1 within 1e-6
    for body in ("sun", "earth"):
        enu = point[body]["direction_enu"]
        norm = math.sqrt(enu["east"] ** 2 + enu["north"] ** 2 + enu["up"] ** 2)
        assert norm == pytest.approx(1.0, abs=1e-6)

        # Three.js mapping verification: scene.x = east, scene.y = up, scene.z = -north
        scene_x = enu["east"]
        scene_y = enu["up"]
        scene_z = -enu["north"]
        assert -1.0 <= scene_x <= 1.0
        assert -1.0 <= scene_y <= 1.0
        assert -1.0 <= scene_z <= 1.0

    # Map extent check: latitude [-90, 90], longitude [-180, 180)
    assert -90.0 <= result_body["site"]["latitude"] <= 90.0
    assert -180.0 <= result_body["site"]["longitude"] < 180.0

    # Source provenance
    assert result_body["meta"]["data_status"] == "fresh"
    assert result_body["meta"]["horizon_mode"] == "geometric"
    assert len(result_body["meta"]["sources"]) == 2
    for source in result_body["meta"]["sources"]:
        assert source["name"] == "NASA/JPL Horizons API"
        assert source["version"] == "DE441"
        assert source["url"].startswith("https://")


def test_observation_cache_hit_workflow(stage_client, stage_repo):
    """Verify identical observation requests produce cached results without provider calls."""
    request_payload = {
        "site": {"latitude": -89.44, "longitude": 222.1},
        "target_time": "2027-07-15T12:00:00Z",
        "observer_height_m": 2.0,
        "visibility_margin_deg": 0.0,
        "horizon_mode": "geometric",
    }

    mock_provider = make_mock_provider("shackleton-sun.json", "shackleton-earth.json")

    def execute(normalized):
        point = calculate_geometric_observation(
            latitude=normalized["site"]["latitude"],
            longitude=normalized["site"]["longitude"],
            target_time=normalized["target_time"],
            observer_height_m=normalized["observer_height_m"],
            visibility_margin_deg=normalized["visibility_margin_deg"],
            provider=mock_provider,
        )
        return {
            "site": normalized["site"],
            "point": point.model_dump(),
            "meta": {
                "model_version": "geometric-now-v1",
                "generated_at": "2026-11-14T12:00:00Z",
                "data_status": "fresh",
                "horizon_mode": "geometric",
                "time_resolution_minutes": None,
                "terrain_dataset_id": None,
                "sources": [s.to_contract_source() for s in point.sources],
            },
        }

    # First run: fresh
    res1 = stage_client.post("/api/v1/ephemeris/now", json=request_payload)
    job_id_1 = res1.json()["job_id"]
    run_once(stage_repo, executor=execute)
    result1 = stage_client.get(f"/api/v1/jobs/{job_id_1}/result").json()
    assert result1["meta"]["data_status"] == "fresh"

    # Second run with same scientific parameters: must be cached without calling executor
    def failing_executor(_):
        raise AssertionError("Executor must NOT be called on a cache hit")

    res2 = stage_client.post("/api/v1/ephemeris/now", json=request_payload)
    job_id_2 = res2.json()["job_id"]
    run_once(stage_repo, executor=failing_executor)
    result2 = stage_client.get(f"/api/v1/jobs/{job_id_2}/result").json()

    assert result2["meta"]["data_status"] == "cached"
    assert result2["point"] == result1["point"]
    assert result2["site"]["longitude"] == -137.9  # Normalized longitude


def test_visibility_margin_strict_inequality():
    """Verify strict inequality when body elevation is between 0 and visibility margin."""
    # Sun elevation is +1.490814 deg in Faustini Rim A fixture
    mock_provider = make_mock_provider("faustini-sun.json", "faustini-earth.json")

    # With 0 deg margin: 1.490814 > 0.0 -> visible is True
    pt_zero = calculate_geometric_observation(
        latitude=-87.45,
        longitude=77.0,
        target_time="2027-07-15T12:00:00Z",
        visibility_margin_deg=0.0,
        provider=mock_provider,
    )
    assert pt_zero.sun.elevation_deg == pytest.approx(1.490814, abs=1e-5)
    assert pt_zero.sun.visible is True

    # With 2.0 deg margin: 1.490814 > (0.0 + 2.0) is False -> visible is False
    pt_margin = calculate_geometric_observation(
        latitude=-87.45,
        longitude=77.0,
        target_time="2027-07-15T12:00:00Z",
        visibility_margin_deg=2.0,
        provider=mock_provider,
    )
    assert pt_margin.sun.elevation_deg == pytest.approx(1.490814, abs=1e-5)
    assert pt_margin.sun.visible is False


# --- Failure Modes and Structured Error Propagation ---


@pytest.mark.parametrize(
    "error_exc,expected_code",
    [
        (
            HorizonsProviderError("No matches found for target"),
            "PROVIDER_ERROR",
        ),
        (
            HorizonsTransportError("Connection timed out"),
            "ASTRONOMY_UNAVAILABLE",
        ),
        (
            HorizonsParseError("No observation rows found between $$SOE and $$EOE"),
            "PROVIDER_ERROR",
        ),
        (
            HorizonsParseError("Observation data missing ('n.a.') in row"),
            "PROVIDER_ERROR",
        ),
        (
            HorizonsParseError("Horizons returned timestamp '2027-Jul-15 12:01:00'"),
            "PROVIDER_ERROR",
        ),
    ],
)
def test_stage2_failure_propagation_to_job(stage_client, stage_repo, error_exc, expected_code):
    """Verify provider failures propagate as structured errors without returning zeroes."""
    request_payload = {
        "site": {"latitude": -89.44, "longitude": 222.1},
        "target_time": "2027-07-15T12:00:00Z",
        "observer_height_m": 2.0,
        "visibility_margin_deg": 0.0,
        "horizon_mode": "geometric",
    }
    submit_res = stage_client.post("/api/v1/ephemeris/now", json=request_payload)
    assert submit_res.status_code == 202
    job_accepted = submit_res.json()
    status_url = job_accepted["status_url"]
    result_url = job_accepted["result_url"]

    def failing_executor(_):
        raise error_exc

    worked = run_once(stage_repo, executor=failing_executor)
    assert worked is True

    # Job status must show failed with structured error
    status_res = stage_client.get(status_url)
    assert status_res.status_code == 200
    status_body = status_res.json()
    validate_schema("Job", status_body)
    assert status_body["status"] == "failed"
    assert status_body["error"]["code"] == expected_code
    assert status_body["error"]["request_id"]

    # Result read must return HTTP 409 JOB_FAILED
    result_res = stage_client.get(result_url)
    assert result_res.status_code == 409
    error_body = result_res.json()
    assert error_body["error"]["code"] == "JOB_FAILED"


# --- Live Stage 2 Control Scenario (Opt-In) ---


@pytest.mark.skipif(
    not os.getenv("TEST_LIVE_HORIZONS"),
    reason="Set TEST_LIVE_HORIZONS to run the live Stage 2 observation workflow",
)
def test_live_observation_workflow_shackleton(stage_client, stage_repo):
    """Live verification of the complete observation workflow against real JPL Horizons API."""
    request_payload = {
        "site": {"name": "Shackleton Live", "latitude": -89.44, "longitude": 222.1},
        "target_time": "2027-07-15T12:00:00Z",
        "observer_height_m": 2.0,
        "visibility_margin_deg": 0.0,
        "horizon_mode": "geometric",
    }

    # Submit job
    res = stage_client.post("/api/v1/ephemeris/now", json=request_payload)
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    # Execute with real Horizons provider
    worked = run_once(stage_repo, executor=execute_observation)
    assert worked is True

    # Fetch result
    result = stage_client.get(f"/api/v1/jobs/{job_id}/result").json()
    validate_schema("NowResult", result)

    assert result["meta"]["data_status"] == "fresh"
    assert result["site"]["longitude"] == -137.9

    point = result["point"]
    # Live Horizons query must agree with Stage 0 DE441 verified ephemeris
    assert point["sun"]["azimuth_deg"] == pytest.approx(177.278712, abs=1e-5)
    assert point["sun"]["elevation_deg"] == pytest.approx(-1.088272, abs=1e-5)
    assert point["sun"]["visible"] is False
    assert point["earth"]["azimuth_deg"] == pytest.approx(142.714718, abs=1e-5)
    assert point["earth"]["elevation_deg"] == pytest.approx(-6.178829, abs=1e-5)
    assert point["earth"]["visible"] is False
    assert point["is_golden_window"] is False

    # Check sources
    sources = result["meta"]["sources"]
    assert len(sources) == 2
    assert all(s["version"] == "DE441" for s in sources)
    assert all("https://ssd.jpl.nasa.gov/api/horizons.api" in s["url"] for s in sources)
