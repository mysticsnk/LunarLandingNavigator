"""Windowed access to prepared lunar elevation GeoTIFF assets."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import Window

from app.terrain.model import (
    MOON_REFERENCE_RADIUS_M,
    TerrainDataError,
    normalize_longitude_exact,
    south_polar_stereographic,
)


class GeoTiffTerrainSource:
    """Sample a single-band south-polar Float32 DEM without loading it into memory."""

    def __init__(
        self,
        path: Path,
        *,
        dataset_id: str,
        model_version: str,
        source_url: str,
        source_frame: str,
        reference_radius_m: float,
    ) -> None:
        if source_frame != "MOON_ME / JPL DE421":
            raise ValueError("terrain source frame must be MOON_ME / JPL DE421")
        if reference_radius_m != MOON_REFERENCE_RADIUS_M:
            raise ValueError("terrain source reference radius does not match the lunar model")
        if not dataset_id or not model_version or not source_url:
            raise ValueError("dataset_id, model_version, and source_url are required")

        self.dataset_id = dataset_id
        self.model_version = model_version
        self.source_url = source_url
        self._environment = rasterio.Env(GDAL_CACHEMAX=128 * 1024 * 1024)
        self._environment.__enter__()
        try:
            self._dataset = rasterio.open(path)
            transform = self._dataset.transform
            projection = self._dataset.crs.to_dict() if self._dataset.crs else {}
            resolution_x, resolution_y = transform.a, -transform.e
            if (
                self._dataset.count != 1
                or self._dataset.dtypes[0] != "float32"
                or self._dataset.width < 2
                or self._dataset.height < 2
                or projection.get("proj") != "stere"
                or projection.get("lat_0") != -90
                or projection.get("lat_ts") != -90
                or projection.get("lon_0") != 0
                or projection.get("x_0", 0) != 0
                or projection.get("y_0", 0) != 0
                or not math.isclose(float(projection.get("R", 0)), MOON_REFERENCE_RADIUS_M)
                or not math.isclose(transform.b, 0.0, abs_tol=1e-12)
                or not math.isclose(transform.d, 0.0, abs_tol=1e-12)
                or resolution_x <= 0.0
                or not math.isclose(resolution_x, resolution_y, rel_tol=0, abs_tol=1e-9)
            ):
                raise ValueError(
                    "terrain GeoTIFF must use the agreed lunar stereographic frame and a "
                    "north-up single-band Float32 grid"
                )
            self.x_min_m = transform.c
            self.y_max_m = transform.f
            self.resolution_m = resolution_x
            self.width = self._dataset.width
            self.height = self._dataset.height
        except Exception:
            if hasattr(self, "_dataset"):
                self._dataset.close()
            self._environment.__exit__(None, None, None)
            raise

    def close(self) -> None:
        self._dataset.close()
        self._environment.__exit__(None, None, None)

    def __enter__(self) -> GeoTiffTerrainSource:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def sample(self, latitude: float, longitude: float) -> float:
        x_m, y_m = south_polar_stereographic(latitude, normalize_longitude_exact(longitude))
        pixel_col, pixel_row = ~self._dataset.transform @ (x_m, y_m)
        col, row = pixel_col - 0.5, pixel_row - 0.5
        if not -0.5 <= col <= self.width - 0.5 or not -0.5 <= row <= self.height - 0.5:
            raise TerrainDataError(
                "outside_coverage", "Coordinate is outside the terrain footprint"
            )

        col = min(max(col, 0.0), self.width - 1.0)
        row = min(max(row, 0.0), self.height - 1.0)
        col0, row0 = min(math.floor(col), self.width - 2), min(math.floor(row), self.height - 2)
        col_fraction, row_fraction = col - col0, row - row0
        values = self._dataset.read(
            1,
            window=Window(col0, row0, 2, 2),
            masked=True,
        )
        weights = (
            (1.0 - col_fraction) * (1.0 - row_fraction),
            col_fraction * (1.0 - row_fraction),
            (1.0 - col_fraction) * row_fraction,
            col_fraction * row_fraction,
        )
        flattened = np.ma.asarray(values).reshape(-1)
        if any(
            np.ma.is_masked(value) and weight > 1e-12
            for value, weight in zip(flattened, weights, strict=True)
        ):
            raise TerrainDataError("no_data", "Terrain interpolation touches a no-data cell")
        samples = tuple(float(value) for value in flattened)
        if any(not math.isfinite(value) for value in samples):
            raise TerrainDataError("no_data", "Terrain interpolation returned a non-finite value")
        return sum(value * weight for value, weight in zip(samples, weights, strict=True))

    def sample_many(self, latitudes: list[float], longitudes: list[float]) -> list[float]:
        if len(latitudes) != len(longitudes):
            raise ValueError("latitude and longitude arrays must have the same length")
        if not latitudes:
            return []

        projected = [
            south_polar_stereographic(latitude, normalize_longitude_exact(longitude))
            for latitude, longitude in zip(latitudes, longitudes, strict=True)
        ]
        x_m, y_m = np.asarray(projected, dtype=np.float64).T
        col = (x_m - self.x_min_m) / self.resolution_m - 0.5
        row = (self.y_max_m - y_m) / self.resolution_m - 0.5
        outside = (col < -0.5) | (col > self.width - 0.5) | (row < -0.5) | (row > self.height - 0.5)
        if np.any(outside):
            raise TerrainDataError(
                "outside_coverage", "Coordinate is outside the terrain footprint"
            )

        col = np.clip(col, 0.0, self.width - 1.0)
        row = np.clip(row, 0.0, self.height - 1.0)
        col0 = np.minimum(np.floor(col).astype(np.int64), self.width - 2)
        row0 = np.minimum(np.floor(row).astype(np.int64), self.height - 2)
        col_fraction, row_fraction = col - col0, row - row0
        left, top = int(col0.min()), int(row0.min())
        right, bottom = int(col0.max()) + 2, int(row0.max()) + 2
        values = self._dataset.read(
            1,
            window=Window(left, top, right - left, bottom - top),
            masked=True,
        )
        local_col, local_row = col0 - left, row0 - top
        samples = np.ma.asarray(
            [
                values[local_row, local_col],
                values[local_row, local_col + 1],
                values[local_row + 1, local_col],
                values[local_row + 1, local_col + 1],
            ]
        ).T
        weights = np.column_stack(
            (
                (1.0 - col_fraction) * (1.0 - row_fraction),
                col_fraction * (1.0 - row_fraction),
                (1.0 - col_fraction) * row_fraction,
                col_fraction * row_fraction,
            )
        )
        masked = np.ma.getmaskarray(samples)
        if np.any(masked & (weights > 1e-12)):
            raise TerrainDataError("no_data", "Terrain interpolation touches a no-data cell")

        data = np.asarray(samples.filled(np.nan), dtype=np.float64)
        if not np.isfinite(data).all():
            raise TerrainDataError("no_data", "Terrain interpolation returned a non-finite value")
        return np.sum(data * weights, axis=1).tolist()
