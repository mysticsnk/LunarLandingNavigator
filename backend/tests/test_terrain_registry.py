"""Controlled registry, coverage, job-freezing, and heightmap tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import numpy as np
import rasterio
from rasterio.transform import from_origin
from sqlalchemy import create_engine, insert

from app.requests import NowRequest
from app.results import ResolvedSite
from app.storage import (
    Repository,
    metadata,
    request_key,
    sites,
    terrain_datasets,
    terrain_regions,
)
from app.worker import terrain_service_for


def terrain_repository(tmp_path):
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            insert(sites),
            {
                "id": "controlled-site",
                "name": "Controlled site",
                "category": "artemis",
                "latitude": -90.0,
                "longitude": 0.0,
                "description": "Controlled test fixture",
                "source_url": "https://example.invalid/site",
                "quickmap_url": None,
                "terrain_region_id": "controlled-region",
            },
        )
    path = tmp_path / "controlled.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=201,
        height=201,
        count=1,
        dtype="float32",
        transform=from_origin(-2010, 2010, 20, 20),
        crs=(
            "+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +x_0=0 +y_0=0 +R=1737400 +units=m +no_defs"
        ),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(np.full((201, 201), 12.5, dtype="float32"), 1)
    repository = Repository(engine, clock=lambda: datetime(2026, 11, 15, tzinfo=UTC))
    dataset_id = "controlled-product-v1"
    with engine.begin() as conn:
        conn.execute(
            insert(terrain_datasets).values(
                id=dataset_id,
                product_version="controlled-fixture",
                source_url="https://example.invalid/controlled-dem",
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                asset_path=str(path),
                processing_version="lunar-south-polar-v1",
                resolution_m=20.0,
                retrieved_at=datetime(2026, 11, 15, tzinfo=UTC),
                attribution="Controlled test fixture",
                ready=1,
            )
        )
        conn.execute(
            insert(terrain_regions).values(
                id="controlled-region",
                dataset_id=dataset_id,
                origin_latitude=-90.0,
                origin_longitude=0.0,
                spacing_m=20.0,
                grid_half_extent_m=1280.0,
            )
        )
    return repository, dataset_id, engine


def test_terrain_registry_resolves_supported_observer_and_persists_provenance(tmp_path):
    repository, dataset_id, engine = terrain_repository(tmp_path)
    request = NowRequest.model_validate(
        {
            "site": {"site_id": "controlled-site"},
            "target_time": "2027-07-15T12:00:00Z",
            "horizon_mode": "terrain",
        }
    )

    normalized = repository.resolve(request)
    coverage = repository.terrain_coverage(-90, 222.1)

    assert normalized["terrain_dataset_id"] == dataset_id
    assert normalized["processing_version"] == "lunar-south-polar-v1"
    assert normalized["site"]["surface_elevation_m"] == 12.5
    assert "terrain_region_id" not in normalized["site"]
    ResolvedSite.model_validate(normalized["site"])
    assert coverage["available"] is True
    assert coverage["longitude"] == -137.9
    assert coverage["dataset_id"] == dataset_id
    assert coverage["region_id"].startswith("custom-")
    engine.dispose()


def test_terrain_request_without_registered_data_reports_no_data(tmp_path):
    repository, _, engine = terrain_repository(tmp_path)
    with engine.begin() as conn:
        conn.execute(terrain_regions.delete())
        conn.execute(terrain_datasets.delete())

    coverage = repository.terrain_coverage(-89.44, 222.1)

    assert coverage == {
        "available": False,
        "latitude": -89.44,
        "longitude": -137.9,
        "region_id": None,
        "dataset_id": None,
        "resolution_m": None,
        "source_url": None,
        "reason": "no_data",
    }
    engine.dispose()


def test_registering_a_new_product_version_preserves_jobs_and_updates_regions(
    tmp_path, monkeypatch
):
    repository, previous_id, engine = terrain_repository(tmp_path)
    asset_path = tmp_path / "verified-fixture.tif"
    asset_path.write_bytes(b"controlled fixture version two")
    digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
    manifest = {
        "path": str(asset_path),
        "preparation_status": "terrain_ready",
        "sha256": digest,
        "product_id": "LDEM_80S_20MPP_ADJ.TIF",
        "version": "controlled-v2",
        "source_url": "https://example.invalid/controlled-dem-v2",
        "resolution_m": 20.0,
    }
    monkeypatch.setattr(
        "tools.prepare_terrain.verify_raster", lambda product, path, expected: manifest
    )

    current_id = repository.register_terrain_dataset(manifest)
    assert current_id == repository.register_terrain_dataset(manifest)
    with engine.connect() as conn:
        current_region_dataset = conn.scalar(
            terrain_regions.select().with_only_columns(terrain_regions.c.dataset_id)
        )

    assert current_region_dataset == current_id
    assert current_id != previous_id
    assert repository.terrain_dataset(previous_id) is not None
    engine.dispose()


def test_terrain_dataset_and_observer_location_are_in_cache_identity(tmp_path):
    repository, dataset_id, engine = terrain_repository(tmp_path)
    request = NowRequest.model_validate(
        {
            "site": {"latitude": -90, "longitude": 0},
            "target_time": "2027-07-15T12:00:00Z",
            "horizon_mode": "terrain",
        }
    )
    normalized = repository.resolve(request)
    changed_dataset = {**normalized, "terrain_dataset_id": "different-version"}
    changed_processing = {**normalized, "processing_version": "different-model"}
    changed_location = {
        **normalized,
        "site": {**normalized["site"], "latitude": -89.9},
    }

    assert normalized["terrain_dataset_id"] == dataset_id
    assert request_key(normalized) != request_key(changed_dataset)
    assert request_key(normalized) != request_key(changed_processing)
    assert request_key(normalized) != request_key(changed_location)
    engine.dispose()


def test_worker_opens_the_resolved_terrain_dataset_version(tmp_path, monkeypatch):
    repository, dataset_id, engine = terrain_repository(tmp_path)
    request = NowRequest.model_validate(
        {
            "site": {"latitude": -90, "longitude": 0},
            "target_time": "2027-07-15T12:00:00Z",
            "horizon_mode": "terrain",
        }
    )
    normalized = repository.resolve(request)
    monkeypatch.setattr("app.worker.get_repository", lambda: repository)

    with terrain_service_for(normalized) as (terrain_service, dataset):
        assert dataset["id"] == dataset_id
        assert dataset["processing_version"] == normalized["processing_version"]
        assert terrain_service.observer_surface.surface_elevation_m == 12.5
        assert terrain_service.observer_surface.dataset_id == dataset_id
    engine.dispose()


def test_registered_site_heightmap_is_bounded_and_uses_local_enu(tmp_path):
    repository, _, engine = terrain_repository(tmp_path)
    heightmap = repository.heightmap("controlled-region")

    assert heightmap["frame"] == "local_enu"
    assert heightmap["width"] == 129
    assert heightmap["height"] == 129
    assert len(heightmap["elevation_m"]) == 129 * 129
    assert heightmap["origin"]["elevation_m"] == 12.5
    engine.dispose()
