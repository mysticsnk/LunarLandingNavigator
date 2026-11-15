"""Lunar south-polar stereographic terrain grid conventions and sampling."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

MOON_REFERENCE_RADIUS_M = 1_737_400.0
SOUTH_POLAR_FRAME = "MOON_ME_DE421"


def normalize_longitude_exact(longitude: float) -> float:
    """Normalize positive-east longitude without rounding physical coordinates."""
    return ((longitude + 180.0) % 360.0) - 180.0


class TerrainDataError(ValueError):
    """A numerical terrain value cannot support the requested sample."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class TerrainSource(Protocol):
    dataset_id: str
    model_version: str
    source_url: str
    resolution_m: float

    def sample(self, latitude: float, longitude: float) -> float: ...


def south_polar_stereographic(latitude: float, longitude: float) -> tuple[float, float]:
    """Project positive-east selenographic coordinates to LOLA south-polar X/Y metres."""
    if not math.isfinite(latitude) or not -90.0 <= latitude <= 90.0:
        raise ValueError("latitude must be finite and in [-90, 90] degrees")
    if not math.isfinite(longitude) or not -180.0 <= longitude < 360.0:
        raise ValueError("longitude must be finite and in [-180, 360) degrees")

    latitude_rad = math.radians(latitude)
    longitude_rad = math.radians(normalize_longitude_exact(longitude))
    rho = 2.0 * MOON_REFERENCE_RADIUS_M * math.tan((math.pi / 2.0 + latitude_rad) / 2.0)
    return rho * math.sin(longitude_rad), rho * math.cos(longitude_rad)


def inverse_south_polar_stereographic(x_m: float, y_m: float) -> tuple[float, float]:
    """Convert LOLA south-polar X/Y metres to planetocentric latitude/longitude degrees."""
    if not math.isfinite(x_m) or not math.isfinite(y_m):
        raise ValueError("projected coordinates must be finite")
    rho = math.hypot(x_m, y_m)
    latitude = -90.0 + math.degrees(2.0 * math.atan2(rho, 2.0 * MOON_REFERENCE_RADIUS_M))
    longitude = 0.0 if rho == 0.0 else math.degrees(math.atan2(x_m, y_m))
    return latitude, normalize_longitude_exact(longitude)


@dataclass(frozen=True)
class TerrainGrid:
    """Single-band float elevation grid in the LOLA south-polar frame.

    ``x_min_m`` and ``y_max_m`` are the outer upper-left grid edges. Rows are
    stored north-to-south and columns west-to-east; elevations are metres above
    the 1,737,400 m LOLA reference sphere. No-data cells must be ``None``.
    """

    dataset_id: str
    model_version: str
    source_url: str
    x_min_m: float
    y_max_m: float
    resolution_m: float
    width: int
    height: int
    elevation_m: tuple[float | None, ...]

    def __post_init__(self) -> None:
        if not self.dataset_id or not self.model_version or not self.source_url:
            raise ValueError("dataset_id, model_version, and source_url are required")
        if not math.isfinite(self.x_min_m) or not math.isfinite(self.y_max_m):
            raise ValueError("grid origin must be finite")
        if not math.isfinite(self.resolution_m) or self.resolution_m <= 0.0:
            raise ValueError("resolution_m must be finite and positive")
        if self.width < 2 or self.height < 2:
            raise ValueError("terrain grid must be at least 2 by 2 cells")
        if len(self.elevation_m) != self.width * self.height:
            raise ValueError("elevation_m length must equal width * height")
        if any(value is not None and not math.isfinite(value) for value in self.elevation_m):
            raise ValueError("elevation_m values must be finite or None for no-data")

    def sample(self, latitude: float, longitude: float) -> float:
        """Bilinearly sample a location; reject out-of-footprint and no-data cells."""
        x_m, y_m = south_polar_stereographic(latitude, longitude)
        col = (x_m - self.x_min_m) / self.resolution_m - 0.5
        row = (self.y_max_m - y_m) / self.resolution_m - 0.5
        if not -0.5 <= col <= self.width - 0.5 or not -0.5 <= row <= self.height - 0.5:
            raise TerrainDataError(
                "outside_coverage", "Coordinate is outside the terrain footprint"
            )

        col = min(max(col, 0.0), self.width - 1.0)
        row = min(max(row, 0.0), self.height - 1.0)
        col0, row0 = min(math.floor(col), self.width - 2), min(math.floor(row), self.height - 2)
        col_fraction, row_fraction = col - col0, row - row0
        indices = (
            row0 * self.width + col0,
            row0 * self.width + col0 + 1,
            (row0 + 1) * self.width + col0,
            (row0 + 1) * self.width + col0 + 1,
        )
        values = tuple(self.elevation_m[index] for index in indices)
        weights = (
            (1.0 - col_fraction) * (1.0 - row_fraction),
            col_fraction * (1.0 - row_fraction),
            (1.0 - col_fraction) * row_fraction,
            col_fraction * row_fraction,
        )
        if any(
            value is None and weight > 1e-12 for value, weight in zip(values, weights, strict=True)
        ):
            raise TerrainDataError("no_data", "Terrain interpolation touches a no-data cell")
        return sum((value or 0.0) * weight for value, weight in zip(values, weights, strict=True))
