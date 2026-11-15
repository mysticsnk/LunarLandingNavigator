"""Contract tests for numerical local ENU heightmap generation."""

from __future__ import annotations

import pytest

from app.terrain.display import build_heightmap


class NorthRisingTerrain:
    dataset_id = "controlled-v1"
    source_url = "https://example.invalid/controlled-dem"

    def sample(self, latitude, longitude):
        return (latitude + 90.0) * 1000.0


def test_heightmap_uses_local_enu_origin_and_north_increasing_rows():
    terrain = NorthRisingTerrain()
    result = build_heightmap(
        {
            "id": terrain.dataset_id,
            "region_id": "controlled-region",
            "processing_version": "controlled-model-v1",
            "origin_latitude": -89.9,
            "origin_longitude": 20.0,
            "spacing_m": 20.0,
            "grid_half_extent_m": 20.0,
            "source_url": terrain.source_url,
            "attribution": "Controlled test data",
        },
        terrain,
    )

    assert result["frame"] == "local_enu"
    assert result["origin"]["elevation_m"] == pytest.approx(100.0)
    assert result["width"] == result["height"] == 3
    assert len(result["elevation_m"]) == result["width"] * result["height"]
    assert result["elevation_m"][3] < result["elevation_m"][6]
    assert result["elevation_m"][4] == pytest.approx(0.0, abs=1e-8)


def test_heightmap_rejects_an_unbounded_grid():
    with pytest.raises(ValueError, match="size limit"):
        build_heightmap(
            {
                "origin_latitude": -89.9,
                "origin_longitude": 20.0,
                "spacing_m": 1.0,
                "grid_half_extent_m": 1000.0,
            },
            NorthRisingTerrain(),
        )
