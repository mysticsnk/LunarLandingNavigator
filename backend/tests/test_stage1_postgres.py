import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import contextmanager
from datetime import timedelta
from importlib import import_module
from pathlib import Path
from threading import Event
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool
from test_stage1_jobs import REQUEST, check_schema, controlled

from app.astronomy import HorizonsProvider
from app.core.config import get_settings
from app.core.database import get_engine
from app.main import create_app
from app.maps.errors import MapServiceError
from app.requests import NowRequest
from app.resources import get_resources
from app.routes import get_csa_fetcher
from app.storage import Repository, get_repository, iso, jobs
from app.worker import HORIZONS_LOCK, execute_observation, run_once

pytestmark = pytest.mark.integration


@pytest.fixture
def pg_repo(monkeypatch, stage_clock):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a dedicated PostgreSQL test database")
    database = make_url(url).database
    if not database or (database.lower() != "test" and not database.lower().endswith("_test")):
        pytest.fail("TEST_DATABASE_URL must target a dedicated database named test or *_test")
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    get_engine.cache_clear()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(url, poolclass=NullPool)
    yield Repository(engine, clock=lambda: stage_clock[0])
    engine.dispose()
    get_engine().dispose()
    get_engine.cache_clear()
    get_settings.cache_clear()


@pytest.fixture
def pg_client(pg_repo):
    app = create_app()
    app.dependency_overrides[get_repository] = lambda: pg_repo
    with TestClient(app) as client:
        yield client


def test_http_observation_lifecycle_with_postgresql_and_controlled_horizons(
    pg_client, pg_repo, monkeypatch
):
    root = Path(__file__).resolve().parents[2]
    fixtures = {
        target: json.loads(
            (root / f"contracts/reference/horizons/shackleton-{target.lower()}.json").read_text(
                encoding="utf-8"
            )
        )["raw_response"]
        for target in ("Sun", "Earth")
    }
    requests = []
    provider_unavailable = False

    def response(request):
        requests.append(request.url.params)
        if provider_unavailable:
            return httpx.Response(503, text="Controlled provider outage")
        target = "Sun" if request.url.params["COMMAND"].strip("'") == "10" else "Earth"
        return httpx.Response(200, json=fixtures[target])

    client = httpx.Client(transport=httpx.MockTransport(response))
    provider = HorizonsProvider(client=client, max_retries=0)
    monkeypatch.setattr("app.worker.HorizonsProvider", lambda **kwargs: provider)

    try:
        assert pg_client.get("/api/v1/map/layers").status_code == 200
        catalog = pg_client.get("/api/v1/sites/shackleton-connecting-ridge")
        assert catalog.status_code == 200
        check_schema("Site", catalog.json())

        app = pg_client.app

        def unavailable_csa():
            raise httpx.ConnectError("Controlled CSA outage")

        app.dependency_overrides[get_csa_fetcher] = lambda: unavailable_csa
        csa_failure = pg_client.get("/api/v1/resources/csa")
        assert csa_failure.status_code == 503
        assert csa_failure.json()["error"]["code"] == "CSA_UNAVAILABLE"
        app.dependency_overrides.pop(get_csa_fetcher)

        request = {
            **REQUEST,
            "site": {"site_id": "shackleton-connecting-ridge"},
            "target_time": "2027-07-15T12:00:00Z",
        }
        accepted = pg_client.post("/api/v1/ephemeris/now", json=request)
        assert accepted.status_code == 202
        check_schema("JobAccepted", accepted.json())
        job_id = accepted.json()["job_id"]
        assert pg_client.get(accepted.json()["result_url"]).status_code == 409
        persisted = pg_repo.job(job_id)
        assert persisted["submitted"] == request
        assert persisted["normalized"]["target_time"] == request["target_time"]
        assert persisted["normalized"]["site"]["site_id"] == "shackleton-connecting-ridge"
        assert persisted["normalized"]["observer_height_m"] == 2.0
        assert persisted["normalized"]["visibility_margin_deg"] == 0.0
        assert persisted["normalized"]["horizon_mode"] == "geometric"

        async def unavailable_map(*args, **kwargs):
            raise MapServiceError(503, "HTTP_503", "Map provider is unavailable")

        map_routes = import_module("app.maps.router")
        monkeypatch.setattr(map_routes, "fetch_image", unavailable_map)
        failed_map = pg_client.get(
            "/api/v1/map/layers/luna_wac_global/image?bbox=-180,-90,180,90&width=64&height=32"
        )
        assert failed_map.status_code == 503
        assert pg_client.get(accepted.json()["status_url"]).json()["status"] == "queued"
        assert run_once(pg_repo, executor=execute_observation)

        status = pg_client.get(accepted.json()["status_url"])
        result_response = pg_client.get(accepted.json()["result_url"])
        assert status.status_code == result_response.status_code == 200
        check_schema("Job", status.json())
        check_schema("NowResult", result_response.json())
        result = result_response.json()
        assert status.json()["status"] == "succeeded"
        assert status.json()["started_at"] and status.json()["finished_at"]
        assert result["point"]["timestamp"] == request["target_time"]
        assert result["site"]["site_id"] == "shackleton-connecting-ridge"
        assert result["site"]["longitude"] == -137.9
        assert result["point"]["sun"]["azimuth_deg"] == pytest.approx(177.278712)
        assert result["point"]["earth"]["azimuth_deg"] == pytest.approx(142.714718)
        assert result["meta"]["data_status"] == "fresh"
        assert result["meta"]["generated_at"] != result["point"]["timestamp"]
        assert all(
            source["fetched_at"] != result["point"]["timestamp"]
            for source in result["meta"]["sources"]
        )
        restarted_engine = create_engine(pg_repo.engine.url, poolclass=NullPool)
        try:
            restarted_repo = Repository(restarted_engine, clock=pg_repo.clock)
            assert restarted_repo.status(job_id)["status"] == "succeeded"
            assert restarted_repo.result(job_id) == result
        finally:
            restarted_engine.dispose()
        assert len(requests) == 2
        assert all(item["START_TIME"] == "'2027-07-15 12:00:00'" for item in requests)
        assert all(item["SITE_COORD"] == "'-137.9,-89.44,0.002000'" for item in requests)

        custom = {
            **request,
            "site": {"name": "Equivalent custom point", "latitude": -89.44, "longitude": -137.9},
        }
        cached_acceptance = pg_client.post("/api/v1/ephemeris/now", json=custom)
        assert cached_acceptance.status_code == 202
        assert run_once(pg_repo, executor=execute_observation)
        cached = pg_client.get(cached_acceptance.json()["result_url"]).json()
        assert cached["site"]["site_id"] is None
        assert cached["site"]["name"] == "Equivalent custom point"
        assert cached["meta"]["data_status"] == "cached"
        assert cached["meta"]["generated_at"] == result["meta"]["generated_at"]
        assert len(requests) == 2

        distinct_margin = {**custom, "visibility_margin_deg": 1.0}
        distinct_acceptance = pg_client.post("/api/v1/ephemeris/now", json=distinct_margin)
        assert distinct_acceptance.status_code == 202
        assert run_once(pg_repo, executor=execute_observation)
        distinct = pg_client.get(distinct_acceptance.json()["result_url"]).json()
        assert distinct["meta"]["data_status"] == "fresh"
        assert distinct["site"]["site_id"] is None
        assert distinct["site"]["name"] == "Equivalent custom point"
        assert distinct["site"]["latitude"] == -89.44
        assert distinct["site"]["longitude"] == -137.9
        assert len(requests) == 4

        provider_unavailable = True
        failed_request = {**custom, "target_time": "2027-07-15T12:01:00Z"}
        failed_acceptance = pg_client.post("/api/v1/ephemeris/now", json=failed_request)
        assert failed_acceptance.status_code == 202
        assert run_once(pg_repo, executor=execute_observation)
        failed_status = pg_client.get(failed_acceptance.json()["status_url"])
        failed_result = pg_client.get(failed_acceptance.json()["result_url"])
        assert failed_status.json()["status"] == "failed"
        assert failed_status.json()["error"]["code"] == "ASTRONOMY_UNAVAILABLE"
        assert failed_result.status_code == 409
        assert failed_result.json()["error"]["code"] == "JOB_FAILED"
        check_schema("ErrorEnvelope", failed_result.json())
    finally:
        client.close()


@pytest.mark.skipif(
    not os.getenv("TEST_LIVE_HORIZONS"),
    reason="Set TEST_LIVE_HORIZONS to run the live PostgreSQL observation workflow",
)
def test_live_observation_job_uses_horizons_and_persists_result(pg_client, pg_repo):
    request = {
        "site": {"site_id": "shackleton-connecting-ridge"},
        "target_time": "2027-07-15T12:00:00Z",
        "horizon_mode": "geometric",
        "visibility_margin_deg": 0.25,
    }
    accepted = pg_client.post("/api/v1/ephemeris/now", json=request)
    assert accepted.status_code == 202
    assert run_once(pg_repo)

    status = pg_client.get(accepted.json()["status_url"]).json()
    result = pg_client.get(accepted.json()["result_url"]).json()
    assert status["status"] == "succeeded"
    assert result["point"]["timestamp"] == request["target_time"]
    assert result["meta"]["data_status"] == "fresh"
    assert result["point"]["sun"]["azimuth_deg"] == pytest.approx(177.278712, abs=1e-5)
    assert result["point"]["earth"]["azimuth_deg"] == pytest.approx(142.714718, abs=1e-5)
    assert [source["name"] for source in result["meta"]["sources"]] == [
        "NASA/JPL Horizons API",
        "NASA/JPL Horizons API",
    ]
    assert all(
        source["url"].startswith("https://ssd.jpl.nasa.gov/api/horizons.api?")
        for source in result["meta"]["sources"]
    )
    assert all(
        source["fetched_at"] != result["point"]["timestamp"] for source in result["meta"]["sources"]
    )
    assert pg_repo.result(accepted.json()["job_id"]) == result


def test_versioned_seed_and_durable_job_cache_on_postgresql(pg_repo):
    catalog = pg_repo.list_sites("apollo", 2, 1)
    assert catalog["total"] == 6 and len(catalog["items"]) == 2
    assert pg_repo.site("shackleton-connecting-ridge")["longitude"] == -137.9
    first = pg_repo.submit(NowRequest.model_validate(REQUEST), str(uuid4()), submitted=REQUEST)[
        "job_id"
    ]
    assert run_once(pg_repo, controlled)
    assert pg_repo.result(first)["meta"]["data_status"] == "fresh"
    second = pg_repo.submit(NowRequest.model_validate(REQUEST), str(uuid4()), submitted=REQUEST)[
        "job_id"
    ]
    assert run_once(pg_repo, lambda value: pytest.fail("A cache hit must not call astronomy"))
    assert pg_repo.result(second)["meta"]["data_status"] == "cached"
    with pg_repo.engine.connect() as connection:
        assert connection.scalar(select(jobs.c.submitted).where(jobs.c.id == first)) == REQUEST


def test_global_provider_slot_and_claim_fencing_on_postgresql(pg_repo, stage_clock):
    with pg_repo.provider_lock(HORIZONS_LOCK) as first:
        assert first
        with Repository(pg_repo.engine).provider_lock(HORIZONS_LOCK) as second:
            assert not second
    job_id = pg_repo.submit(NowRequest.model_validate(REQUEST), str(uuid4()), submitted=REQUEST)[
        "job_id"
    ]
    old = pg_repo.claim(5)
    assert old["id"] == job_id
    assert Repository(pg_repo.engine, pg_repo.clock).claim(5) is None
    stage_clock[0] += timedelta(seconds=6)
    new = pg_repo.claim(5)
    assert new["lease_token"] != old["lease_token"]
    assert pg_repo.finish(new, result=controlled(new["normalized"]))
    assert not pg_repo.finish(old, error={"code": "stale"})
    assert pg_repo.status(job_id)["status"] == "succeeded"


def test_parallel_csa_cold_cache_requests_share_one_refresh_on_postgresql(
    pg_repo, stage_clock, monkeypatch
):
    started, release, contended = Event(), Event(), Event()
    waiter = Repository(pg_repo.engine, pg_repo.clock)
    original_lock = waiter.provider_lock
    calls = []

    @contextmanager
    def observed_lock(key):
        with original_lock(key) as acquired:
            if not acquired:
                contended.set()
            yield acquired

    def fetch():
        calls.append(1)
        started.set()
        assert release.wait(5), "Timed out releasing the controlled CSA fetch"
        return {"items": [], "fetched_at": iso(stage_clock[0])}

    monkeypatch.setattr(waiter, "provider_lock", observed_lock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(get_resources, pg_repo, 1, fetch)
        try:
            assert started.wait(3), "The controlled CSA fetch did not start"
            second = pool.submit(get_resources, waiter, 10, fetch)
            assert contended.wait(3), "The second request did not observe the active refresh"
            with pytest.raises(TimeoutError):
                second.result(timeout=0.05)
        finally:
            release.set()
        fresh, cached = first.result(timeout=5), second.result(timeout=5)
    assert calls == [1]
    assert fresh["data_status"] == "fresh" and cached["data_status"] == "cached"
    assert fresh["items"] == cached["items"] == []
    assert fresh["fetched_at"] == cached["fetched_at"]
