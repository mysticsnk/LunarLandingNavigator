"""Curved-surface local horizon calculations over numerical lunar terrain."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.terrain.model import (
    MOON_REFERENCE_RADIUS_M,
    TerrainDataError,
    TerrainSource,
    normalize_longitude_exact,
)

MAX_LOLA_RELIEF_M = 10_792.0
MAX_OBSERVER_HEIGHT_M = 20.0


class TerrainCoverageError(ValueError):
    """Requested observer or horizon ray is not supported by numerical terrain."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def horizon_search_distance_m(
    observer_height_m: float,
    *,
    reference_radius_m: float = MOON_REFERENCE_RADIUS_M,
    maximum_relief_m: float = MAX_LOLA_RELIEF_M,
) -> float:
    """Return where maximum known relief falls below the local horizontal plane."""
    if (
        not math.isfinite(observer_height_m)
        or not 0.0 <= observer_height_m <= MAX_OBSERVER_HEIGHT_M
    ):
        raise ValueError("observer_height_m must be finite and in [0, 20] metres")
    if not math.isfinite(reference_radius_m) or reference_radius_m <= 0.0:
        raise ValueError("reference_radius_m must be finite and positive")
    if not math.isfinite(maximum_relief_m) or maximum_relief_m <= observer_height_m:
        raise ValueError("maximum_relief_m must exceed observer_height_m")
    observer_radius_m = reference_radius_m + observer_height_m
    target_radius_m = reference_radius_m + maximum_relief_m
    turn_angle = (
        math.acos(target_radius_m / observer_radius_m)
        if observer_radius_m > target_radius_m
        else 0.0
    )
    return _distance_to_horizon(
        observer_radius_m, 0.0, turn_angle, reference_radius_m, maximum_relief_m
    )


@dataclass(frozen=True)
class ObserverSurface:
    latitude: float
    longitude: float
    surface_elevation_m: float
    observer_height_m: float
    observer_position_mcmf_m: tuple[float, float, float]
    dataset_id: str
    model_version: str


@dataclass(frozen=True)
class HorizonResult:
    azimuth_deg: float
    horizon_elevation_deg: float
    max_search_distance_m: float
    sample_step_m: float
    observer: ObserverSurface
    support_status: str = "supported"


class TerrainHorizonService:
    """Resolve an observer and evaluate terrain elevation at a requested azimuth."""

    def __init__(
        self,
        grid: TerrainSource,
        *,
        latitude: float,
        longitude: float,
        observer_height_m: float = 2.0,
        sample_step_m: float | None = None,
    ) -> None:
        if not math.isfinite(latitude) or not -90.0 <= latitude <= 90.0:
            raise ValueError("latitude must be finite and in [-90, 90] degrees")
        if not math.isfinite(longitude) or not -180.0 <= longitude < 360.0:
            raise ValueError("longitude must be finite and in [-180, 360) degrees")
        if not math.isfinite(observer_height_m) or not 0.0 <= observer_height_m <= 20.0:
            raise ValueError("observer_height_m must be finite and in [0, 20] metres")
        self.grid = grid
        self.latitude = latitude
        self.longitude = normalize_longitude_exact(longitude)
        self.observer_height_m = observer_height_m
        self.sample_step_m = grid.resolution_m / 2.0 if sample_step_m is None else sample_step_m
        if (
            not math.isfinite(self.sample_step_m)
            or self.sample_step_m <= 0.0
            or self.sample_step_m > grid.resolution_m
        ):
            raise ValueError("sample_step_m must be positive and no greater than grid resolution")
        try:
            self.surface_elevation_m = grid.sample(self.latitude, self.longitude)
        except TerrainDataError as exc:
            raise TerrainCoverageError(exc.reason, str(exc)) from exc
        radius_m = MOON_REFERENCE_RADIUS_M + self.surface_elevation_m + observer_height_m
        self.observer_position_mcmf_m = self._position_mcmf(self.latitude, self.longitude, radius_m)

    @property
    def observer_surface(self) -> ObserverSurface:
        """Return resolved source surface and actual MCMF observer position."""
        return ObserverSurface(
            latitude=self.latitude,
            longitude=self.longitude,
            surface_elevation_m=self.surface_elevation_m,
            observer_height_m=self.observer_height_m,
            observer_position_mcmf_m=self.observer_position_mcmf_m,
            dataset_id=self.grid.dataset_id,
            model_version=self.grid.model_version,
        )

    def horizon_elevation(self, azimuth_deg: float) -> HorizonResult:
        """Find the greatest curved-Moon apparent terrain elevation along one azimuth."""
        if not math.isfinite(azimuth_deg):
            raise ValueError("azimuth_deg must be finite")
        azimuth = azimuth_deg % 360.0
        max_distance_m = math.pi * MOON_REFERENCE_RADIUS_M
        first_distance_m = math.ceil(1.5 * self.grid.resolution_m / self.sample_step_m)
        first_distance_m *= self.sample_step_m
        azimuth_rad = math.radians(azimuth)
        latitude_rad = math.radians(self.latitude)
        longitude_rad = math.radians(self.longitude)

        up = (
            math.cos(latitude_rad) * math.cos(longitude_rad),
            math.cos(latitude_rad) * math.sin(longitude_rad),
            math.sin(latitude_rad),
        )
        north = (
            -math.sin(latitude_rad) * math.cos(longitude_rad),
            -math.sin(latitude_rad) * math.sin(longitude_rad),
            math.cos(latitude_rad),
        )
        east = (-math.sin(longitude_rad), math.cos(longitude_rad), 0.0)
        tangent = tuple(
            math.cos(azimuth_rad) * north[index] + math.sin(azimuth_rad) * east[index]
            for index in range(3)
        )
        observer_radius_m = math.sqrt(sum(value * value for value in self.observer_position_mcmf_m))
        maximum_relief_m = max(MAX_LOLA_RELIEF_M, self.surface_elevation_m)
        max_elevation_deg = -90.0

        distance_m = first_distance_m
        while distance_m <= max_distance_m:
            try:
                latitude, longitude = self._destination(up, tangent, distance_m)
                surface_elevation_m = self.grid.sample(latitude, longitude)
            except TerrainDataError as exc:
                raise TerrainCoverageError(exc.reason, str(exc)) from exc
            target_radius_m = MOON_REFERENCE_RADIUS_M + surface_elevation_m
            maximum_relief_m = max(maximum_relief_m, surface_elevation_m)
            target = self._position_mcmf(latitude, longitude, target_radius_m)
            delta = tuple(target[i] - self.observer_position_mcmf_m[i] for i in range(3))
            east_component = sum(delta[i] * east[i] for i in range(3))
            north_component = sum(delta[i] * north[i] for i in range(3))
            up_component = sum(delta[i] * up[i] for i in range(3))
            angle = math.degrees(
                math.atan2(up_component, math.hypot(east_component, north_component))
            )
            max_elevation_deg = max(max_elevation_deg, angle)
            turn_angle = (
                math.acos((MOON_REFERENCE_RADIUS_M + maximum_relief_m) / observer_radius_m)
                if observer_radius_m > MOON_REFERENCE_RADIUS_M + maximum_relief_m
                else 0.0
            )
            max_distance_m = _distance_to_horizon(
                observer_radius_m,
                max_elevation_deg,
                turn_angle,
                MOON_REFERENCE_RADIUS_M,
                maximum_relief_m,
            )
            if distance_m >= max_distance_m:
                break
            distance_m = min(distance_m + self.sample_step_m, max_distance_m)

        return HorizonResult(
            azimuth_deg=azimuth,
            horizon_elevation_deg=max_elevation_deg,
            max_search_distance_m=max_distance_m,
            sample_step_m=self.sample_step_m,
            observer=self.observer_surface,
        )

    @staticmethod
    def _position_mcmf(
        latitude: float, longitude: float, radius_m: float
    ) -> tuple[float, float, float]:
        latitude_rad = math.radians(latitude)
        longitude_rad = math.radians(longitude)
        return (
            radius_m * math.cos(latitude_rad) * math.cos(longitude_rad),
            radius_m * math.cos(latitude_rad) * math.sin(longitude_rad),
            radius_m * math.sin(latitude_rad),
        )

    @staticmethod
    def _destination(
        up: tuple[float, float, float],
        tangent: tuple[float, float, float],
        distance_m: float,
    ) -> tuple[float, float]:
        angle = distance_m / MOON_REFERENCE_RADIUS_M
        target = tuple(up[i] * math.cos(angle) + tangent[i] * math.sin(angle) for i in range(3))
        latitude = math.degrees(math.atan2(target[2], math.hypot(target[0], target[1])))
        longitude = math.degrees(math.atan2(target[1], target[0]))
        return latitude, normalize_longitude_exact(longitude)


def _relief_elevation_deg(
    observer_radius_m: float,
    distance_m: float,
    reference_radius_m: float,
    maximum_relief_m: float,
) -> float:
    angle = distance_m / reference_radius_m
    target_radius_m = reference_radius_m + maximum_relief_m
    return math.degrees(
        math.atan2(
            target_radius_m * math.cos(angle) - observer_radius_m,
            target_radius_m * math.sin(angle),
        )
    )


def _distance_to_horizon(
    observer_radius_m: float,
    horizon_elevation_deg: float,
    turn_angle: float,
    reference_radius_m: float,
    maximum_relief_m: float,
) -> float:
    low = turn_angle * reference_radius_m
    high = math.pi * reference_radius_m
    if (
        _relief_elevation_deg(observer_radius_m, low, reference_radius_m, maximum_relief_m)
        <= horizon_elevation_deg
    ):
        return low
    for _ in range(64):
        middle = (low + high) / 2.0
        if (
            _relief_elevation_deg(observer_radius_m, middle, reference_radius_m, maximum_relief_m)
            > horizon_elevation_deg
        ):
            low = middle
        else:
            high = middle
    return high
