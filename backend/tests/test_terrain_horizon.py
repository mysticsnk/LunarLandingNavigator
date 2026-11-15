"""Controlled numerical tests for lunar terrain sampling and horizon geometry."""

from __future__ import annotations

import math

import pytest

from app.terrain import (
    MOON_REFERENCE_RADIUS_M,
    TerrainCoverageError,
    TerrainGrid,
    TerrainHorizonService,
    horizon_search_distance_m,
    inverse_south_polar_stereographic,
    normalize_longitude_exact,
    south_polar_stereographic,
)
from app.terrain.model import TerrainDataError


class AnalyticTerrain:
    dataset_id = "controlled-numerical-surface"
    model_version = "test-lola-sphere-v1"
    source_url = "https://example.invalid/controlled-fixture"
    resolution_m = 1_000.0

    def __init__(self, center, *, ridges=(), max_distance_m=None, no_data=None):
        self.center = center
        self.ridges = ridges
        self.max_distance_m = max_distance_m or math.pi * MOON_REFERENCE_RADIUS_M
        self.no_data = no_data

    def sample(self, latitude, longitude):
        if self.center is None:
            return 0.0
        observer_lat, observer_lon = self.center
        distance_m, bearing_deg = great_circle_distance_and_bearing(
            observer_lat, observer_lon, latitude, longitude
        )
        if distance_m > self.max_distance_m:
            raise TerrainDataError("outside_coverage", "outside analytic terrain support")
        if self.no_data and self.no_data(distance_m, bearing_deg):
            raise TerrainDataError("no_data", "no-data gap")
        height_m = 0.0
        for ridge_bearing, ridge_distance, ridge_half_width, ridge_height in self.ridges:
            if (
                abs((bearing_deg - ridge_bearing + 180.0) % 360.0 - 180.0) <= 0.15
                and abs(distance_m - ridge_distance) <= ridge_half_width
            ):
                height_m = max(height_m, ridge_height)
        return height_m


def great_circle_distance_and_bearing(latitude1, longitude1, latitude2, longitude2):
    """Independent closed-form fixture geometry for placing controlled ridges."""
    phi1, lam1 = math.radians(latitude1), math.radians(longitude1)
    phi2, lam2 = math.radians(latitude2), math.radians(longitude2)
    observer = (
        math.cos(phi1) * math.cos(lam1),
        math.cos(phi1) * math.sin(lam1),
        math.sin(phi1),
    )
    target = (
        math.cos(phi2) * math.cos(lam2),
        math.cos(phi2) * math.sin(lam2),
        math.sin(phi2),
    )
    dot = sum(observer[i] * target[i] for i in range(3))
    angle = math.acos(max(-1.0, min(1.0, dot)))
    north = (-math.sin(phi1) * math.cos(lam1), -math.sin(phi1) * math.sin(lam1), math.cos(phi1))
    east = (-math.sin(lam1), math.cos(lam1), 0.0)
    tangent = tuple(target[i] - dot * observer[i] for i in range(3))
    bearing = (
        math.degrees(
            math.atan2(
                sum(tangent[i] * east[i] for i in range(3)),
                sum(tangent[i] * north[i] for i in range(3)),
            )
        )
        % 360.0
    )
    return angle * MOON_REFERENCE_RADIUS_M, bearing


def make_grid(*, values=None, resolution_m=20.0, width=4, height=4):
    values = values or (0.0,) * (width * height)
    return TerrainGrid(
        dataset_id="controlled-grid",
        model_version="controlled-model-v1",
        source_url="https://example.invalid/controlled-fixture",
        x_min_m=-resolution_m * width / 2.0,
        y_max_m=resolution_m * height / 2.0,
        resolution_m=resolution_m,
        width=width,
        height=height,
        elevation_m=tuple(values),
    )


def test_south_polar_projection_preserves_lunar_longitude_equivalence():
    projected = south_polar_stereographic(-89.44, 222.1)
    assert projected == pytest.approx(south_polar_stereographic(-89.44, -137.9), abs=1e-8)
    latitude, longitude = inverse_south_polar_stereographic(*projected)
    assert latitude == pytest.approx(-89.44, abs=1e-10)
    assert longitude == pytest.approx(-137.9, abs=1e-10)
    assert normalize_longitude_exact(222.1234567) == pytest.approx(-137.8765433, abs=1e-12)


def test_grid_interpolation_preserves_row_orientation_units_and_nodata():
    grid = make_grid(values=(10.0, 20.0, 30.0, 40.0), width=2, height=2)
    assert grid.sample(*inverse_south_polar_stereographic(-10.0, 10.0)) == pytest.approx(10.0)
    assert grid.sample(*inverse_south_polar_stereographic(10.0, 10.0)) == pytest.approx(20.0)
    assert grid.sample(*inverse_south_polar_stereographic(-10.0, -10.0)) == pytest.approx(30.0)
    assert grid.sample(*inverse_south_polar_stereographic(10.0, -10.0)) == pytest.approx(40.0)

    missing = make_grid(values=(10.0, None, 30.0, 40.0), width=2, height=2)
    with pytest.raises(ValueError, match="no-data"):
        missing.sample(-90.0, 0.0)


def test_observer_reports_source_surface_height_separately_from_observer_height():
    values = (120.0, 120.0, 120.0, 120.0)
    service = TerrainHorizonService(
        make_grid(values=values, width=2, height=2),
        latitude=-90.0,
        longitude=222.1,
        observer_height_m=2.0,
    )
    assert service.observer_surface.surface_elevation_m == 120.0
    assert service.observer_surface.observer_height_m == 2.0
    x, y, z = service.observer_surface.observer_position_mcmf_m
    assert math.sqrt(x * x + y * y + z * z) == pytest.approx(
        MOON_REFERENCE_RADIUS_M + 122.0, abs=1e-6
    )


def test_smooth_reference_sphere_horizon_accounts_for_lunar_curvature():
    source = AnalyticTerrain(center=(-89.44, -137.9))
    service = TerrainHorizonService(source, latitude=-89.44, longitude=222.1, observer_height_m=2.0)
    result = service.horizon_elevation(90.0)
    assert result.horizon_elevation_deg == pytest.approx(-0.087, abs=0.02)
    assert result.max_search_distance_m > horizon_search_distance_m(2.0)
    assert result.support_status == "supported"


def test_observer_height_changes_curved_surface_horizon():
    source = AnalyticTerrain(center=(-89.44, -137.9))
    low = TerrainHorizonService(
        source, latitude=-89.44, longitude=-137.9, observer_height_m=0.0
    ).horizon_elevation(35.0)
    high = TerrainHorizonService(
        source, latitude=-89.44, longitude=-137.9, observer_height_m=20.0
    ).horizon_elevation(35.0)
    assert high.horizon_elevation_deg < low.horizon_elevation_deg


def test_ridge_direction_near_and_distant_obstacles_and_independent_reference():
    center = (-89.44, -137.9)
    near_only = AnalyticTerrain(center, ridges=((90.0, 5_000.0, 1_000.0, 10.0),))
    near_and_distant = AnalyticTerrain(
        center,
        ridges=(
            (90.0, 5_000.0, 1_000.0, 10.0),
            (90.0, 100_000.0, 2_000.0, 5_000.0),
        ),
    )
    near_east = TerrainHorizonService(
        near_only, latitude=center[0], longitude=center[1], observer_height_m=0.0
    ).horizon_elevation(90.0)
    far_east = TerrainHorizonService(
        near_and_distant, latitude=center[0], longitude=center[1], observer_height_m=0.0
    ).horizon_elevation(90.0)
    west = TerrainHorizonService(
        near_and_distant, latitude=center[0], longitude=center[1], observer_height_m=0.0
    ).horizon_elevation(270.0)

    assert near_east.horizon_elevation_deg > west.horizon_elevation_deg
    assert far_east.horizon_elevation_deg > near_east.horizon_elevation_deg
    assert west.horizon_elevation_deg < 0.0

    distance_m = 100_000.0
    target_radius_m = MOON_REFERENCE_RADIUS_M + 5_000.0
    observer_radius_m = MOON_REFERENCE_RADIUS_M
    angle = distance_m / MOON_REFERENCE_RADIUS_M
    direct_geometry_deg = math.degrees(
        math.atan2(
            target_radius_m * math.cos(angle) - observer_radius_m,
            target_radius_m * math.sin(angle),
        )
    )
    assert far_east.horizon_elevation_deg == pytest.approx(direct_geometry_deg, abs=0.15)


def test_finer_radial_sampling_converges_for_a_broad_ridge():
    center = (-89.44, -137.9)
    source = AnalyticTerrain(center, ridges=((45.0, 30_000.0, 2_000.0, 800.0),))
    coarse = TerrainHorizonService(
        source,
        latitude=center[0],
        longitude=center[1],
        observer_height_m=2.0,
        sample_step_m=500.0,
    ).horizon_elevation(45.0)
    fine = TerrainHorizonService(
        source,
        latitude=center[0],
        longitude=center[1],
        observer_height_m=2.0,
        sample_step_m=250.0,
    ).horizon_elevation(45.0)
    assert fine.horizon_elevation_deg == pytest.approx(coarse.horizon_elevation_deg, abs=0.02)


def test_missing_data_and_insufficient_surrounding_coverage_are_unavailable():
    center = (-89.44, -137.9)
    missing = AnalyticTerrain(
        center,
        no_data=lambda distance, bearing: bearing > 89.8
        and bearing < 90.2
        and 10_000 < distance < 11_000,
    )
    service = TerrainHorizonService(missing, latitude=center[0], longitude=center[1])
    with pytest.raises(TerrainCoverageError, match="no-data") as no_data:
        service.horizon_elevation(90.0)
    assert no_data.value.reason == "no_data"

    boundary = AnalyticTerrain(center, max_distance_m=10_000.0)
    boundary_service = TerrainHorizonService(boundary, latitude=center[0], longitude=center[1])
    with pytest.raises(TerrainCoverageError, match="outside") as outside:
        boundary_service.horizon_elevation(90.0)
    assert outside.value.reason == "outside_coverage"


def test_search_distance_exceeds_observer_height_only_lunar_horizon():
    assert horizon_search_distance_m(2.0) > horizon_search_distance_m(20.0)
    assert horizon_search_distance_m(20.0) > 190_000.0
