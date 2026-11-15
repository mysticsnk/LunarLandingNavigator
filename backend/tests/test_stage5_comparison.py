from copy import deepcopy

import pytest
from test_contract import fixture
from test_stage1_jobs import check_schema

from app.core.problems import APIProblem
from app.requests import ComparisonRequest
from app.storage import request_key
from app.worker import execute_job, run_once

ROOT_REQUEST = fixture("comparison-request.json")

REQUEST = {
    "scenarios": [
        {
            "label": "Shackleton July",
            "site": {"site_id": "shackleton-connecting-ridge"},
            "start_time": "2027-07-15T12:00:00Z",
        },
        {
            "label": "Custom August",
            "site": {"latitude": -87.45, "longitude": 222.1},
            "start_time": "2027-08-15T12:00:00+00:00",
        },
    ],
    "duration_days": 14,
    "step_minutes": 120,
    "horizon_mode": "geometric",
    "observer_height_m": 2,
    "visibility_margin_deg": 0,
}


def test_comparison_request_accepts_catalog_and_custom_sites_with_independent_dates():
    request = ComparisonRequest.model_validate(REQUEST)

    assert [scenario.label for scenario in request.scenarios] == [
        "Shackleton July",
        "Custom August",
    ]
    assert request.scenarios[0].start_time.isoformat() == "2027-07-15T12:00:00+00:00"
    assert request.scenarios[1].start_time.isoformat() == "2027-08-15T12:00:00+00:00"


@pytest.mark.parametrize(
    "changes",
    [
        {"scenarios": REQUEST["scenarios"][:1]},
        {"scenarios": REQUEST["scenarios"] * 4},
        {
            "scenarios": [
                REQUEST["scenarios"][0],
                {**REQUEST["scenarios"][1], "label": REQUEST["scenarios"][0]["label"]},
            ]
        },
        {"duration_days": 0},
        {"duration_days": 31},
        {"step_minutes": 90},
        {"observer_height_m": 21},
        {"visibility_margin_deg": 6},
        {"horizon_mode": "automatic"},
        {"unexpected": True},
        {
            "scenarios": [
                REQUEST["scenarios"][0],
                {**REQUEST["scenarios"][1], "start_time": "2049-12-31T12:00:00Z"},
            ]
        },
        {
            "scenarios": [
                REQUEST["scenarios"][0],
                {**REQUEST["scenarios"][1], "start_time": "2027-08-15T12:00:00"},
            ]
        },
        {
            "scenarios": [
                REQUEST["scenarios"][0],
                {
                    **REQUEST["scenarios"][1],
                    "site": {"site_id": "site", "latitude": 0, "longitude": 0},
                },
            ]
        },
    ],
)
def test_comparison_request_rejects_invalid_scenarios_and_shared_settings(changes):
    with pytest.raises(ValueError):
        ComparisonRequest.model_validate({**REQUEST, **changes})


def test_comparison_request_accepts_period_ending_at_exclusive_supported_boundary():
    request = {
        **REQUEST,
        "duration_days": 1,
        "scenarios": [
            {**REQUEST["scenarios"][0], "start_time": "2049-12-31T00:00:00Z"},
            {**REQUEST["scenarios"][1], "start_time": "2049-12-31T00:00:00Z"},
        ],
    }

    assert ComparisonRequest.model_validate(request).duration_days == 1


def test_comparison_cache_identity_preserves_order_labels_dates_and_model_versions():
    normalized = {
        "kind": "comparison",
        "ranking_version": "v1",
        "duration_days": 1,
        "step_minutes": 360,
        "horizon_mode": "terrain",
        "observer_height_m": 2,
        "visibility_margin_deg": 0,
        "scenarios": [
            {
                "label": "A",
                "site": {"latitude": -89, "longitude": 10, "surface_elevation_m": 100},
                "start_time": "2027-07-15T00:00:00Z",
                "model_version": "terrain-v1",
                "terrain_dataset_id": "dataset-a",
                "processing_version": "process-v1",
            },
            {
                "label": "B",
                "site": {"latitude": -88, "longitude": 20, "surface_elevation_m": 200},
                "start_time": "2027-07-16T00:00:00Z",
                "model_version": "terrain-v2",
                "terrain_dataset_id": "dataset-b",
                "processing_version": "process-v2",
            },
        ],
    }

    for changed in (
        {**normalized, "scenarios": list(reversed(normalized["scenarios"]))},
        {
            **normalized,
            "scenarios": [
                {**normalized["scenarios"][0], "label": "Other"},
                normalized["scenarios"][1],
            ],
        },
        {
            **normalized,
            "scenarios": [
                {**normalized["scenarios"][0], "start_time": "2027-07-16T00:00:00Z"},
                normalized["scenarios"][1],
            ],
        },
        {
            **normalized,
            "scenarios": [
                {**normalized["scenarios"][0], "terrain_dataset_id": "dataset-c"},
                normalized["scenarios"][1],
            ],
        },
    ):
        assert request_key(normalized) != request_key(changed)


def test_comparison_job_lifecycle_and_cache_hit(stage_client, stage_repo):
    accepted = stage_client.post("/api/v1/ephemeris/compare", json=ROOT_REQUEST)
    assert accepted.status_code == 202
    check_schema("JobAccepted", accepted.json())
    assert accepted.json()["kind"] == "comparison"
    assert stage_client.get(accepted.json()["result_url"]).status_code == 409
    normalized = stage_repo.job(accepted.json()["job_id"])["normalized"]
    assert [scenario["label"] for scenario in normalized["scenarios"]] == [
        "Synthetic A",
        "Synthetic B",
    ]
    assert [scenario["start_time"] for scenario in normalized["scenarios"]] == [
        "2027-07-15T00:00:00Z",
        "2027-07-15T00:00:00Z",
    ]
    assert [scenario["site"]["site_id"] for scenario in normalized["scenarios"]] == [None, None]

    fixture_result = fixture("comparison-result.json")
    assert run_once(stage_repo, executor=lambda _: fixture_result)
    status = stage_client.get(accepted.json()["status_url"]).json()
    assert status["status"] == "succeeded", status
    result_response = stage_client.get(accepted.json()["result_url"])
    assert result_response.status_code == 200
    check_schema("ComparisonResult", result_response.json())
    assert result_response.json()["ranking_version"] == "v1"

    cached = stage_client.post("/api/v1/ephemeris/compare", json=ROOT_REQUEST)
    assert cached.status_code == 202
    assert run_once(stage_repo, executor=lambda _: pytest.fail("Cache hit must not execute"))
    cached_result = stage_client.get(cached.json()["result_url"]).json()
    assert cached_result["meta"]["data_status"] == "cached"
    assert cached_result["meta"]["generated_at"] == fixture_result["meta"]["generated_at"]


def test_comparison_submission_resolves_catalog_and_custom_sites(stage_client, stage_repo):
    request = deepcopy(ROOT_REQUEST)
    request["scenarios"][1]["site"] = {"site_id": "test-artemis"}
    accepted = stage_client.post("/api/v1/ephemeris/compare", json=request)

    assert accepted.status_code == 202
    normalized = stage_repo.job(accepted.json()["job_id"])["normalized"]
    assert [scenario["site"]["site_id"] for scenario in normalized["scenarios"]] == [
        None,
        "test-artemis",
    ]


def test_comparison_worker_fails_explicitly_without_service():
    with pytest.raises(APIProblem, match="Comparison calculation service is not integrated"):
        execute_job({"kind": "comparison"})


def test_comparison_job_stores_structured_failure_without_service(stage_client, stage_repo):
    accepted = stage_client.post("/api/v1/ephemeris/compare", json=ROOT_REQUEST)
    assert accepted.status_code == 202
    assert run_once(stage_repo, executor=execute_job)

    status = stage_client.get(accepted.json()["status_url"]).json()
    assert status["status"] == "failed"
    assert status["error"]["code"] == "COMPARISON_UNAVAILABLE"
    failure = stage_client.get(accepted.json()["result_url"])
    assert failure.status_code == 409
    assert failure.json()["error"]["code"] == "JOB_FAILED"


def test_terrain_comparison_rejects_when_any_scenario_has_no_coverage(
    stage_client, stage_repo, monkeypatch
):
    calls = []

    def coverage(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            return (
                {
                    "id": "dataset-test",
                    "processing_version": "terrain-test-v1",
                    "surface_elevation_m": 0.0,
                    "region_id": "region-test",
                },
                None,
            )
        return None, "outside_coverage"

    monkeypatch.setattr(
        stage_repo,
        "terrain_dataset_for",
        coverage,
    )
    response = stage_client.post(
        "/api/v1/ephemeris/compare",
        json={**ROOT_REQUEST, "horizon_mode": "terrain"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TERRAIN_UNAVAILABLE"
    assert response.json()["error"]["details"][0]["field"] == "scenarios.1.site"
    assert len(calls) == 2
