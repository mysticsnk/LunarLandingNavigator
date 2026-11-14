"""Tests for Stage 4 terrain-aware astronomy integration service.

Verifies observer resolution, altitude handling, terrain horizon evaluation,
visibility margin thresholds, direction vector invariance, timeline window
modifications (shorten, split, remove), and structured failure on missing terrain.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.astronomy import (
    calculate_geometric_observation,
    calculate_geometric_timeline,
    calculate_observation,
    calculate_terrain_observation,
    calculate_terrain_timeline,
    calculate_timeline,
)
from app.astronomy.horizons import HorizonsProvider
from app.terrain import (
    MOON_REFERENCE_RADIUS_M,
    TerrainCoverageError,
    TerrainHorizonService,
)
from app.terrain.model import TerrainDataError


def great_circle_distance_and_bearing(
    latitude1: float, longitude1: float, latitude2: float, longitude2: float
) -> tuple[float, float]:
    """Calculate great-circle spherical distance (metres) and bearing (degrees) on the Moon."""
    phi1, lam1 = math.radians(latitude1), math.radians(longitude1)
    phi2, lam2 = math.radians(latitude2), math.radians(longitude2)
    obs = (
        math.cos(phi1) * math.cos(lam1),
        math.cos(phi1) * math.sin(lam1),
        math.sin(phi1),
    )
    tgt = (
        math.cos(phi2) * math.cos(lam2),
        math.cos(phi2) * math.sin(lam2),
        math.sin(phi2),
    )
    dot = max(-1.0, min(1.0, sum(obs[i] * tgt[i] for i in range(3))))
    angle = math.acos(dot)
    north = (-math.sin(phi1) * math.cos(lam1), -math.sin(phi1) * math.sin(lam1), math.cos(phi1))
    east = (-math.sin(lam1), math.cos(lam1), 0.0)
    tangent = tuple(tgt[i] - dot * obs[i] for i in range(3))
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


class ControlledAnalyticTerrain:
    """Deterministic synthetic terrain source for testing terrain-aware visibility."""

    dataset_id = "controlled-test-dem"
    model_version = "stage4-lola-test-v1"
    source_url = "https://example.invalid/controlled-terrain"
    resolution_m = 500.0

    def __init__(
        self,
        center: tuple[float, float],
        base_elevation_m: float = 0.0,
        peak_elevation_m: float | None = None,
        ridges: tuple[tuple[float, float, float, float], ...] = (),
        no_data: bool = False,
        outside_coverage: bool = False,
    ) -> None:
        self.center = center
        self.base_elevation_m = base_elevation_m
        self.peak_elevation_m = peak_elevation_m
        self.ridges = ridges  # (azimuth_deg, distance_m, half_width_m, height_m)
        self.no_data = no_data
        self.outside_coverage = outside_coverage

    def sample(self, latitude: float, longitude: float) -> float:
        if self.outside_coverage:
            raise TerrainDataError("outside_coverage", "Sample point is outside terrain coverage")
        if self.no_data:
            raise TerrainDataError("no_data", "Sample point falls in a no-data gap")

        dist_m, bearing_deg = great_circle_distance_and_bearing(
            self.center[0], self.center[1], latitude, longitude
        )

        # Center peak for elevated mountain summit tests
        if dist_m < 600.0 and self.peak_elevation_m is not None:
            return self.peak_elevation_m

        elevation = self.base_elevation_m
        for r_az, r_dist, r_width, r_height in self.ridges:
            az_diff = abs((bearing_deg - r_az + 180.0) % 360.0 - 180.0)
            dist_diff = abs(dist_m - r_dist)
            if az_diff <= 1.5 and dist_diff <= r_width:
                elevation = max(elevation, self.base_elevation_m + r_height)

        return elevation


def _make_mock_provider(
    sun_az: float,
    sun_el: float,
    earth_az: float,
    earth_el: float,
    captured_altitudes: list[float] | None = None,
) -> HorizonsProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(httpx.QueryParams(request.url.query))
        target_cmd = params.get("COMMAND", "").replace("'", "")
        site_coord = params.get("SITE_COORD", "").replace("'", "")

        if captured_altitudes is not None and site_coord:
            parts = site_coord.split(",")
            if len(parts) == 3:
                captured_altitudes.append(float(parts[2]))

        start_time_str = params.get("START_TIME", "").replace("'", "")
        try:
            dt = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
        except Exception:
            dt = datetime(2027, 7, 15, 12, 0, 0)
        dt_str = dt.strftime("%Y-%b-%d %H:%M:%S")

        step_size = params.get("STEP_SIZE", "").replace("'", "")
        stop_time_str = params.get("STOP_TIME", "").replace("'", "")

        if "m" in step_size and stop_time_str:
            step_m = int(step_size.replace("m", ""))
            dt_stop = datetime.strptime(stop_time_str, "%Y-%m-%d %H:%M:%S")
            lines = []
            curr = dt
            while curr <= dt_stop:
                c_str = curr.strftime("%Y-%b-%d %H:%M:%S")
                if target_cmd == "10":
                    lines.append(f" {c_str},*,i,  {sun_az:.6f},    {sun_el:.6f},")
                else:
                    lines.append(f" {c_str},*,i,  {earth_az:.6f},    {earth_el:.6f},")
                curr += timedelta(minutes=step_m)
        else:
            if target_cmd == "10":
                lines = [f" {dt_str},*,i,  {sun_az:.6f},    {sun_el:.6f},"]
            else:
                lines = [f" {dt_str},*,i,  {earth_az:.6f},    {earth_el:.6f},"]

        text = "$$SOE\n" + "\n".join(lines) + "\n$$EOE"
        return httpx.Response(
            200,
            json={
                "result": text,
                "signature": {"source": "NASA/JPL Horizons API", "version": "1.2"},
            },
        )

    return HorizonsProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_terrain_mode_resolves_surface_and_passes_correct_altitude_to_horizons():
    """Task 1: Verify actual surface elevation + observer height is passed to Horizons."""
    center = (-89.44, -137.9)
    # Surface elevation is 1,200 metres
    grid = ControlledAnalyticTerrain(center=center, base_elevation_m=1200.0)
    service = TerrainHorizonService(
        grid, latitude=center[0], longitude=center[1], observer_height_m=5.0
    )

    assert service.surface_elevation_m == 1200.0
    assert service.observer_height_m == 5.0

    captured_alts: list[float] = []
    provider = _make_mock_provider(120.0, 5.0, 150.0, 10.0, captured_altitudes=captured_alts)

    point = calculate_terrain_observation(
        latitude=center[0],
        longitude=center[1],
        target_time="2027-07-15T12:00:00Z",
        terrain_service=service,
        observer_height_m=5.0,
        provider=provider,
    )

    # 1200m surface + 5m observer = 1205m = 1.205 km
    assert len(captured_alts) == 2
    for alt_km in captured_alts:
        assert math.isclose(alt_km, 1.205, abs_tol=1e-5)

    assert point.surface_elevation_m == 1200.0
    assert point.terrain_dataset_id == "controlled-test-dem"


def test_object_above_zero_but_below_ridge_is_blocked():
    """Task 2 & 5: Sun above 0° geometric horizon but below physical ridge is blocked."""
    center = (-89.44, -137.9)
    # Ridge at azimuth 90°, distance 10 km, height 600m -> horizon ~ +3.4°
    grid = ControlledAnalyticTerrain(
        center=center,
        base_elevation_m=0.0,
        ridges=((90.0, 10_000.0, 1_000.0, 600.0),),
    )
    service = TerrainHorizonService(
        grid, latitude=center[0], longitude=center[1], observer_height_m=2.0
    )

    # Sun elevation is +2.0° (positive, so geometrically visible, but below ridge)
    provider = _make_mock_provider(sun_az=90.0, sun_el=2.0, earth_az=180.0, earth_el=10.0)

    # Terrain observation: blocked by ridge
    terrain_pt = calculate_terrain_observation(
        latitude=center[0],
        longitude=center[1],
        target_time="2027-07-15T12:00:00Z",
        terrain_service=service,
        provider=provider,
    )

    # Geometric observation: visible
    geom_pt = calculate_geometric_observation(
        latitude=center[0],
        longitude=center[1],
        target_time="2027-07-15T12:00:00Z",
        provider=provider,
    )

    assert geom_pt.sun.visible is True
    assert geom_pt.sun.horizon_elevation_deg == 0.0

    assert terrain_pt.sun.visible is False
    assert terrain_pt.sun.horizon_elevation_deg > 2.0  # Ridge is higher than Sun
    assert not terrain_pt.is_golden_window


def test_direction_vectors_remain_astronomical_direction_when_blocked():
    """Task 2: Obstruction must not move the celestial body in the sky."""
    center = (-89.44, -137.9)
    grid = ControlledAnalyticTerrain(
        center=center,
        base_elevation_m=0.0,
        ridges=((90.0, 10_000.0, 1_000.0, 800.0),),
    )
    service = TerrainHorizonService(
        grid, latitude=center[0], longitude=center[1], observer_height_m=2.0
    )
    provider = _make_mock_provider(sun_az=90.0, sun_el=2.0, earth_az=180.0, earth_el=10.0)

    terrain_pt = calculate_terrain_observation(
        latitude=center[0],
        longitude=center[1],
        target_time="2027-07-15T12:00:00Z",
        terrain_service=service,
        provider=provider,
    )

    geom_pt = calculate_geometric_observation(
        latitude=center[0],
        longitude=center[1],
        target_time="2027-07-15T12:00:00Z",
        provider=provider,
    )

    # Sun is blocked in terrain mode
    assert terrain_pt.sun.visible is False

    # Unit ENU directions must be identical to geometric mode and normalized
    assert math.isclose(
        terrain_pt.sun.direction_enu.east, geom_pt.sun.direction_enu.east, abs_tol=1e-6
    )
    assert math.isclose(
        terrain_pt.sun.direction_enu.north, geom_pt.sun.direction_enu.north, abs_tol=1e-6
    )
    assert math.isclose(terrain_pt.sun.direction_enu.up, geom_pt.sun.direction_enu.up, abs_tol=1e-6)

    norm_sq = (
        terrain_pt.sun.direction_enu.east**2
        + terrain_pt.sun.direction_enu.north**2
        + terrain_pt.sun.direction_enu.up**2
    )
    assert math.isclose(norm_sq, 1.0, abs_tol=1e-6)


def test_sun_and_earth_have_independent_horizon_thresholds():
    """Task 2 & 5: Sun and Earth horizons are evaluated along their respective azimuths."""
    center = (-89.44, -137.9)
    # High ridge at 90° (Sun direction), flat at 270° (Earth direction)
    grid = ControlledAnalyticTerrain(
        center=center,
        base_elevation_m=0.0,
        ridges=((90.0, 10_000.0, 1_000.0, 700.0),),
    )
    service = TerrainHorizonService(
        grid, latitude=center[0], longitude=center[1], observer_height_m=2.0
    )
    provider = _make_mock_provider(sun_az=90.0, sun_el=5.0, earth_az=270.0, earth_el=5.0)

    point = calculate_terrain_observation(
        latitude=center[0],
        longitude=center[1],
        target_time="2027-07-15T12:00:00Z",
        terrain_service=service,
        provider=provider,
    )

    assert point.sun.horizon_elevation_deg > 3.0  # Faces 700m ridge
    assert point.earth.horizon_elevation_deg < 0.1  # Faces flat terrain
    assert point.sun.horizon_elevation_deg != point.earth.horizon_elevation_deg


def test_visibility_margin_changes_threshold_correctly():
    """Task 2 & 5: Non-zero visibility margin increases the required clearance."""
    center = (-89.44, -137.9)
    grid = ControlledAnalyticTerrain(center=center, base_elevation_m=0.0)
    service = TerrainHorizonService(
        grid, latitude=center[0], longitude=center[1], observer_height_m=2.0
    )

    # Flat curved moon horizon is slightly below 0° (-0.08°)
    # Sun elevation is +0.5°
    provider = _make_mock_provider(sun_az=90.0, sun_el=0.5, earth_az=180.0, earth_el=10.0)

    # Margin 0.0°: 0.5 > -0.08 + 0.0 -> visible
    pt0 = calculate_terrain_observation(
        latitude=center[0],
        longitude=center[1],
        target_time="2027-07-15T12:00:00Z",
        terrain_service=service,
        visibility_margin_deg=0.0,
        provider=provider,
    )
    assert pt0.sun.visible is True

    # Margin 1.0°: 0.5 > -0.08 + 1.0 = 0.92 -> NOT visible
    pt1 = calculate_terrain_observation(
        latitude=center[0],
        longitude=center[1],
        target_time="2027-07-15T12:00:00Z",
        terrain_service=service,
        visibility_margin_deg=1.0,
        provider=provider,
    )
    assert pt1.sun.visible is False


def test_higher_observer_unblocks_visibility():
    """Task 5: Raising observer height lowers horizon elevation and restores visibility."""
    center = (-89.44, -137.9)
    # Ridge 5 km away, 30m high
    grid = ControlledAnalyticTerrain(
        center=center,
        base_elevation_m=0.0,
        ridges=((90.0, 5_000.0, 500.0, 30.0),),
    )

    # Sun elevation is +0.28°
    provider = _make_mock_provider(sun_az=90.0, sun_el=0.28, earth_az=180.0, earth_el=10.0)

    # At 2m height: horizon is higher than 0.28° -> blocked
    svc_low = TerrainHorizonService(
        grid, latitude=center[0], longitude=center[1], observer_height_m=2.0
    )
    pt_low = calculate_terrain_observation(
        latitude=center[0],
        longitude=center[1],
        target_time="2027-07-15T12:00:00Z",
        terrain_service=svc_low,
        observer_height_m=2.0,
        provider=provider,
    )
    assert pt_low.sun.visible is False

    # At 20m height: horizon drops below 0.28° -> visible
    svc_high = TerrainHorizonService(
        grid, latitude=center[0], longitude=center[1], observer_height_m=20.0
    )
    pt_high = calculate_terrain_observation(
        latitude=center[0],
        longitude=center[1],
        target_time="2027-07-15T12:00:00Z",
        terrain_service=svc_high,
        observer_height_m=20.0,
        provider=provider,
    )
    assert pt_high.sun.visible is True
    assert pt_high.sun.horizon_elevation_deg < pt_low.sun.horizon_elevation_deg


def test_missing_terrain_produces_structured_failure():
    """Task 3 & 5: Coverage failure or no-data gap raises TerrainCoverageError without fallback."""
    center = (-89.44, -137.9)

    # Case 1: Outside coverage
    grid_out = ControlledAnalyticTerrain(center=center, outside_coverage=True)
    with pytest.raises(TerrainCoverageError, match="outside"):
        TerrainHorizonService(grid_out, latitude=center[0], longitude=center[1])

    # Case 2: No-data gap
    grid_nodata = ControlledAnalyticTerrain(center=center, no_data=True)
    with pytest.raises(TerrainCoverageError, match="no-data"):
        TerrainHorizonService(grid_nodata, latitude=center[0], longitude=center[1])


def test_negative_horizon_mode_difference():
    """Task 4: High peak has negative horizon, allowing visibility of negative elevation."""
    center = (-89.44, -137.9)
    # Observer is on a 3,000 m mountain summit (within 600m radius), surrounding plain is at 0m
    grid = ControlledAnalyticTerrain(center=center, base_elevation_m=0.0, peak_elevation_m=3000.0)
    service = TerrainHorizonService(
        grid, latitude=center[0], longitude=center[1], observer_height_m=2.0
    )

    # Sun is at -0.5° (negative elevation relative to horizontal plane)
    provider = _make_mock_provider(sun_az=90.0, sun_el=-0.5, earth_az=180.0, earth_el=10.0)

    geom_pt = calculate_geometric_observation(
        latitude=center[0],
        longitude=center[1],
        target_time="2027-07-15T12:00:00Z",
        provider=provider,
    )
    terrain_pt = calculate_terrain_observation(
        latitude=center[0],
        longitude=center[1],
        target_time="2027-07-15T12:00:00Z",
        terrain_service=service,
        provider=provider,
    )

    # In geometric mode: -0.5 <= 0.0 -> NOT visible
    assert geom_pt.sun.visible is False
    assert geom_pt.sun.horizon_elevation_deg == 0.0

    # In terrain mode on 3000m peak: horizon dips significantly below 0° (approx -3.3°)
    assert terrain_pt.sun.horizon_elevation_deg < -2.0
    # Sun at -0.5° is above the dipping terrain horizon (-3.3°) -> VISIBLE!
    assert terrain_pt.sun.visible is True


def test_terrain_timeline_modifies_windows():
    """Task 3 & 5: Verify terrain shortens, splits, or removes timeline windows."""
    center = (-89.44, -137.9)
    start_dt = datetime(2027, 7, 15, 0, 0, tzinfo=UTC)

    # Setup provider for 4 points with Sun az=90, elev=2.0 (always geometrically visible)
    # Earth always visible at 10.0
    provider = _make_mock_provider(sun_az=90.0, sun_el=2.0, earth_az=180.0, earth_el=10.0)

    # Geometric timeline: 1 window of 24h
    geom_tl = calculate_geometric_timeline(
        latitude=center[0],
        longitude=center[1],
        start_time=start_dt,
        duration_days=1,
        step_minutes=360,
        provider=provider,
    )
    assert len(geom_tl.sunlight_windows) == 1
    assert geom_tl.sunlight_windows[0].duration_hours == 24.0

    # Case A: Terrain removes window (ridge at 90° with horizon ~3.5° > Sun 2.0°)
    grid_high = ControlledAnalyticTerrain(
        center=center,
        base_elevation_m=0.0,
        ridges=((90.0, 10_000.0, 2_000.0, 800.0),),
    )
    svc_high = TerrainHorizonService(
        grid_high, latitude=center[0], longitude=center[1], observer_height_m=2.0
    )
    tl_removed = calculate_terrain_timeline(
        latitude=center[0],
        longitude=center[1],
        start_time=start_dt,
        duration_days=1,
        step_minutes=360,
        terrain_service=svc_high,
        provider=provider,
    )
    assert len(tl_removed.sunlight_windows) == 0
    assert tl_removed.summary.sunlit_hours == 0.0
    assert tl_removed.summary.sunlit_pct == 0.0

    # Case B: Dynamic timeline where Sun az rotates and terrain ridge only blocks specific hours
    # 00:00 az=0 el=2.0; 06:00 az=90 el=2.0; 12:00 az=180 el=2.0; 18:00 az=270 el=2.0
    def rotating_handler(request: httpx.Request) -> httpx.Response:
        params = dict(httpx.QueryParams(request.url.query))
        target_cmd = params.get("COMMAND", "").replace("'", "")
        step_m = 360
        lines = []
        for i in range(5):  # 4 samples + 1 endpoint
            curr = start_dt + i * timedelta(minutes=step_m)
            c_str = curr.strftime("%Y-%b-%d %H:%M:%S")
            az = (i * 90.0) % 360.0
            if target_cmd == "10":
                lines.append(f" {c_str},*,i,  {az:.6f},    2.000000,")
            else:
                lines.append(f" {c_str},*,i,  180.000000,    10.000000,")
        text = "$$SOE\n" + "\n".join(lines) + "\n$$EOE"
        return httpx.Response(
            200, json={"result": text, "signature": {"source": "NASA/JPL Horizons API"}}
        )

    rot_provider = HorizonsProvider(
        client=httpx.Client(transport=httpx.MockTransport(rotating_handler))
    )

    # Ridge at 90° blocks sample 1 (06:00, az=90°).
    # Samples 0 (az=0), 2 (az=180), 3 (az=270) are unblocked.
    # Pattern: True, False, True, True -> splits into two windows!
    tl_split = calculate_terrain_timeline(
        latitude=center[0],
        longitude=center[1],
        start_time=start_dt,
        duration_days=1,
        step_minutes=360,
        terrain_service=svc_high,
        provider=rot_provider,
    )
    assert len(tl_split.sunlight_windows) == 2
    # Window 1: [00:00, 06:00), 6h
    assert tl_split.sunlight_windows[0].start_time == "2027-07-15T00:00:00Z"
    assert tl_split.sunlight_windows[0].end_time == "2027-07-15T06:00:00Z"
    assert tl_split.sunlight_windows[0].duration_hours == 6.0
    # Window 2: [12:00, 24:00), 12h
    assert tl_split.sunlight_windows[1].start_time == "2027-07-15T12:00:00Z"
    assert tl_split.sunlight_windows[1].end_time == "2027-07-16T00:00:00Z"
    assert tl_split.sunlight_windows[1].duration_hours == 12.0


def test_unified_observation_and_timeline_entrypoints():
    """Verify unified calculate_observation and calculate_timeline entrypoints."""
    center = (-89.44, -137.9)
    grid = ControlledAnalyticTerrain(center=center, base_elevation_m=0.0)
    service = TerrainHorizonService(
        grid, latitude=center[0], longitude=center[1], observer_height_m=2.0
    )
    provider = _make_mock_provider(sun_az=90.0, sun_el=2.0, earth_az=180.0, earth_el=10.0)

    # 1. Geometric mode via unified function
    geom_pt = calculate_observation(
        latitude=center[0],
        longitude=center[1],
        target_time="2027-07-15T12:00:00Z",
        horizon_mode="geometric",
        provider=provider,
    )
    assert geom_pt.sun.horizon_elevation_deg == 0.0

    # 2. Terrain mode via unified function
    terrain_pt = calculate_observation(
        latitude=center[0],
        longitude=center[1],
        target_time="2027-07-15T12:00:00Z",
        horizon_mode="terrain",
        terrain_service=service,
        provider=provider,
    )
    assert terrain_pt.terrain_dataset_id == "controlled-test-dem"

    # 3. Terrain mode without service raises ValueError
    with pytest.raises(ValueError, match="terrain_service is required"):
        calculate_observation(
            latitude=center[0],
            longitude=center[1],
            target_time="2027-07-15T12:00:00Z",
            horizon_mode="terrain",
            provider=provider,
        )

    # 4. Timeline unified
    geom_tl = calculate_timeline(
        latitude=center[0],
        longitude=center[1],
        start_time="2027-07-15T00:00:00Z",
        duration_days=1,
        step_minutes=360,
        horizon_mode="geometric",
        provider=provider,
    )
    assert geom_tl.terrain_dataset_id is None

    terrain_tl = calculate_timeline(
        latitude=center[0],
        longitude=center[1],
        start_time="2027-07-15T00:00:00Z",
        duration_days=1,
        step_minutes=360,
        horizon_mode="terrain",
        terrain_service=service,
        provider=provider,
    )
    assert terrain_tl.terrain_dataset_id == "controlled-test-dem"
