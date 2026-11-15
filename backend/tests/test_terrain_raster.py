"""Controlled GeoTIFF sampling tests for the production terrain reader."""

from __future__ import annotations

from math import isclose

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.terrain import MOON_REFERENCE_RADIUS_M, inverse_south_polar_stereographic
from app.terrain.model import TerrainDataError
from app.terrain.raster import GeoTiffTerrainSource


def write_raster(path, values, *, nodata=-9999.0):
    raster = np.asarray(values, dtype="float32")
    rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=raster.shape[1],
        height=raster.shape[0],
        count=1,
        dtype="float32",
        transform=from_origin(-100.0, 100.0, 20.0, 20.0),
        crs=(
            "+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +x_0=0 +y_0=0 +R=1737400 +units=m +no_defs"
        ),
        nodata=nodata,
    ).close()
    with rasterio.open(path, "r+") as dataset:
        dataset.write(raster, 1)


def terrain_source(path):
    return GeoTiffTerrainSource(
        path,
        dataset_id="controlled-product-v1",
        model_version="terrain-horizon-test-v1",
        source_url="https://example.invalid/controlled-dem",
        source_frame="MOON_ME / JPL DE421",
        reference_radius_m=MOON_REFERENCE_RADIUS_M,
    )


def location_at_pixel_center(col, row):
    return inverse_south_polar_stereographic(-100 + (col + 0.5) * 20, 100 - (row + 0.5) * 20)


def test_geotiff_reader_bilinearly_samples_float32_values_and_closes(tmp_path):
    path = tmp_path / "controlled.tif"
    write_raster(
        path, [[0, 10, 20, 30], [40, 50, 60, 70], [80, 90, 100, 110], [120, 130, 140, 150]]
    )
    latitude, longitude = location_at_pixel_center(1, 1)

    with terrain_source(path) as source:
        assert isclose(source.sample(latitude, longitude), 50.0, abs_tol=1e-9)
        assert isclose(source.sample(*location_at_pixel_center(1.5, 1.5)), 75.0, abs_tol=1e-9)
        assert source.resolution_m == 20.0


def test_geotiff_reader_rejects_no_data_and_outside_coverage(tmp_path):
    path = tmp_path / "controlled.tif"
    write_raster(path, [[1, 2, 3, 4], [5, -9999, 7, 8], [9, 10, 11, 12], [13, 14, 15, 16]])
    with terrain_source(path) as source:
        with pytest.raises(TerrainDataError, match="no-data") as no_data:
            source.sample(*location_at_pixel_center(1, 1))
        assert no_data.value.reason == "no_data"

        with pytest.raises(TerrainDataError) as outside:
            source.sample(-30.0, 0.0)
        assert outside.value.reason == "outside_coverage"


def test_geotiff_reader_rejects_an_unagreed_reference_frame(tmp_path):
    with pytest.raises(ValueError, match="source frame"):
        GeoTiffTerrainSource(
            tmp_path / "missing.tif",
            dataset_id="controlled-product-v1",
            model_version="terrain-horizon-test-v1",
            source_url="https://example.invalid/controlled-dem",
            source_frame="unknown",
            reference_radius_m=MOON_REFERENCE_RADIUS_M,
        )


def test_geotiff_reader_rejects_an_unagreed_crs(tmp_path):
    path = tmp_path / "earth.tif"
    rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="float32",
        transform=from_origin(-100.0, 100.0, 20.0, 20.0),
        crs="EPSG:4326",
    ).close()

    with pytest.raises(ValueError, match="lunar stereographic frame"):
        terrain_source(path)
