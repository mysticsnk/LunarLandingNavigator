"""Numerical lunar terrain sampling and local horizon calculations."""

from app.terrain.horizon import (
    HorizonResult,
    ObserverSurface,
    TerrainCoverageError,
    TerrainHorizonService,
    horizon_search_distance_m,
)
from app.terrain.model import (
    MOON_REFERENCE_RADIUS_M,
    SOUTH_POLAR_FRAME,
    TerrainGrid,
    TerrainSource,
    inverse_south_polar_stereographic,
    normalize_longitude_exact,
    south_polar_stereographic,
)

__all__ = [
    "MOON_REFERENCE_RADIUS_M",
    "SOUTH_POLAR_FRAME",
    "HorizonResult",
    "ObserverSurface",
    "TerrainCoverageError",
    "TerrainGrid",
    "TerrainSource",
    "TerrainHorizonService",
    "horizon_search_distance_m",
    "inverse_south_polar_stereographic",
    "normalize_longitude_exact",
    "south_polar_stereographic",
]
