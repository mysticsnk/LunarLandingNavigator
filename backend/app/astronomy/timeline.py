"""Geometric timeline observation service for lunar surface sites.

Calculates multi-day topocentric time series, continuous visibility intervals
(sunlight, Earth visibility, and golden windows), and summary metrics.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.astronomy.horizons import (
    HorizonsParseError,
    HorizonsProvider,
    normalize_longitude,
)
from app.astronomy.observation import (
    MAX_SUPPORTED_TIME,
    MIN_SUPPORTED_TIME,
    BodyObservation,
    ObservationPoint,
    SourceMetadata,
    calculate_direction_enu,
)

if TYPE_CHECKING:
    from app.terrain.horizon import HorizonResult, TerrainHorizonService

ALLOWED_STEP_MINUTES = (15, 30, 60, 120, 180, 360)


class Window(BaseModel):
    """Half-open continuous visibility interval [start_time, end_time)."""

    model_config = ConfigDict(extra="forbid")

    start_time: str
    end_time: str
    duration_hours: float = Field(gt=0.0)


class Summary(BaseModel):
    """Aggregate summary metrics across a timeline observation period."""

    model_config = ConfigDict(extra="forbid")

    sunlit_hours: float = Field(ge=0.0, le=720.0)
    sunlit_pct: float = Field(ge=0.0, le=100.0)
    earth_visible_hours: float = Field(ge=0.0, le=720.0)
    earth_visible_pct: float = Field(ge=0.0, le=100.0)
    golden_hours: float = Field(ge=0.0, le=720.0)
    golden_pct: float = Field(ge=0.0, le=100.0)
    longest_golden_window_hours: float = Field(ge=0.0, le=720.0)
    average_sun_elevation_deg: float = Field(ge=-90.0, le=90.0)
    next_sunset_at: str | None = None
    next_earthset_at: str | None = None


TimelineSummary = Summary


class TimelineCalculationResult(BaseModel):
    """Calculated timeline result containing samples, intervals, and summary."""

    model_config = ConfigDict(extra="forbid")

    start_time: str
    end_time: str
    step_minutes: int
    total_samples: int = Field(ge=1)
    points: list[ObservationPoint]
    sunlight_windows: list[Window]
    earth_visibility_windows: list[Window]
    golden_windows: list[Window]
    summary: Summary
    sources: list[SourceMetadata] = Field(default_factory=list, exclude=True)
    surface_elevation_m: float = Field(default=0.0, exclude=True)
    terrain_dataset_id: str | None = Field(default=None, exclude=True)


def generate_time_grid(
    start_time: datetime | str,
    duration_days: int,
    step_minutes: int,
) -> list[datetime]:
    """Generate exact half-open UTC time grid [start_time, end_time) excluding end_time."""
    if isinstance(start_time, str):
        dt = datetime.fromisoformat(start_time)
    else:
        dt = start_time

    if dt.tzinfo is None:
        raise ValueError("start_time must include an explicit timezone")

    dt_start = dt.astimezone(UTC)
    if not (MIN_SUPPORTED_TIME <= dt_start < MAX_SUPPORTED_TIME):
        min_iso = MIN_SUPPORTED_TIME.isoformat()
        max_iso = MAX_SUPPORTED_TIME.isoformat()
        raise ValueError(f"start_time must be within [{min_iso}, {max_iso})")

    if not isinstance(duration_days, int) or not 1 <= duration_days <= 30:
        raise ValueError("duration_days must be an integer between 1 and 30")

    if step_minutes not in ALLOWED_STEP_MINUTES:
        raise ValueError(f"step_minutes must be one of {ALLOWED_STEP_MINUTES}")

    end_time = dt_start + timedelta(days=duration_days)
    if end_time > MAX_SUPPORTED_TIME:
        raise ValueError(
            f"start_time + duration_days must not exceed {MAX_SUPPORTED_TIME.isoformat()}"
        )

    total_samples = duration_days * 1440 // step_minutes
    step = timedelta(minutes=step_minutes)
    return [dt_start + i * step for i in range(total_samples)]


def detect_continuous_windows(
    timestamps: list[datetime],
    flags: list[bool],
    step: timedelta,
    end_time: datetime,
) -> list[Window]:
    """Detect continuous intervals where flag is True.

    A sample at timestamps[i] represents [timestamps[i], min(timestamps[i] + step, end_time)).
    Consecutive true samples merge into a single continuous window.
    False samples split the window.
    """
    intervals: list[tuple[datetime, datetime]] = []
    for ts, flag in zip(timestamps, flags, strict=True):
        if flag:
            a = ts
            b = min(ts + step, end_time)
            if intervals and intervals[-1][1] == a:
                intervals[-1] = (intervals[-1][0], b)
            else:
                intervals.append((a, b))

    return [
        Window(
            start_time=a.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end_time=b.strftime("%Y-%m-%dT%H:%M:%SZ"),
            duration_hours=(b - a).total_seconds() / 3600.0,
        )
        for a, b in intervals
    ]


def calculate_timeline_summary(
    *,
    points: list[ObservationPoint],
    sunlight_windows: list[Window],
    earth_visibility_windows: list[Window],
    golden_windows: list[Window],
    total_period_hours: float,
) -> Summary:
    """Compute aggregate summary metrics from sample points and continuous windows."""
    if not points:
        raise ValueError("points list must not be empty")
    if total_period_hours <= 0:
        raise ValueError("total_period_hours must be positive")

    sunlit_hours = sum(w.duration_hours for w in sunlight_windows)
    sunlit_pct = 100.0 * sunlit_hours / total_period_hours

    earth_visible_hours = sum(w.duration_hours for w in earth_visibility_windows)
    earth_visible_pct = 100.0 * earth_visible_hours / total_period_hours

    golden_hours = sum(w.duration_hours for w in golden_windows)
    golden_pct = 100.0 * golden_hours / total_period_hours

    longest_golden_window_hours = max((w.duration_hours for w in golden_windows), default=0.0)
    average_sun_elevation_deg = sum(p.sun.elevation_deg for p in points) / len(points)

    # Next sunset/earthset: first true-to-false transition observed strictly inside points
    next_sunset_at: str | None = None
    for prev, curr in zip(points, points[1:], strict=False):
        if prev.sun.visible and not curr.sun.visible:
            next_sunset_at = curr.timestamp
            break

    next_earthset_at: str | None = None
    for prev, curr in zip(points, points[1:], strict=False):
        if prev.earth.visible and not curr.earth.visible:
            next_earthset_at = curr.timestamp
            break

    return Summary(
        sunlit_hours=sunlit_hours,
        sunlit_pct=sunlit_pct,
        earth_visible_hours=earth_visible_hours,
        earth_visible_pct=earth_visible_pct,
        golden_hours=golden_hours,
        golden_pct=golden_pct,
        longest_golden_window_hours=longest_golden_window_hours,
        average_sun_elevation_deg=average_sun_elevation_deg,
        next_sunset_at=next_sunset_at,
        next_earthset_at=next_earthset_at,
    )


def calculate_geometric_timeline(
    *,
    latitude: float,
    longitude: float,
    start_time: datetime | str,
    duration_days: int,
    step_minutes: int,
    observer_height_m: float = 2.0,
    visibility_margin_deg: float = 0.0,
    provider: HorizonsProvider | None = None,
) -> TimelineCalculationResult:
    """Calculate multi-day geometric observation timeline for Sun and Earth."""
    if not math.isfinite(latitude) or not -90.0 <= latitude <= 90.0:
        raise ValueError("Latitude must be a finite number between -90 and 90 degrees")

    if not math.isfinite(longitude) or not -180.0 <= longitude < 360.0:
        raise ValueError("Longitude must be a finite number in [-180, 360) degrees")

    if not math.isfinite(observer_height_m) or not 0.0 <= observer_height_m <= 20.0:
        raise ValueError("observer_height_m must be between 0 and 20 metres")

    if not math.isfinite(visibility_margin_deg) or not 0.0 <= visibility_margin_deg <= 5.0:
        raise ValueError("visibility_margin_deg must be between 0 and 5 degrees")

    time_grid = generate_time_grid(start_time, duration_days, step_minutes)
    dt_start = time_grid[0]
    dt_end = dt_start + timedelta(days=duration_days)
    step = timedelta(minutes=step_minutes)

    norm_lon = normalize_longitude(longitude)
    active_provider = provider if provider is not None else HorizonsProvider()

    sun_series = active_provider.query_body_series(
        target="Sun",
        latitude=latitude,
        longitude=norm_lon,
        altitude_m=observer_height_m,
        start_time=dt_start,
        stop_time=dt_end,
        step_minutes=step_minutes,
    )
    earth_series = active_provider.query_body_series(
        target="Earth",
        latitude=latitude,
        longitude=norm_lon,
        altitude_m=observer_height_m,
        start_time=dt_start,
        stop_time=dt_end,
        step_minutes=step_minutes,
    )

    if len(sun_series) != len(earth_series):
        raise HorizonsParseError(
            f"Incompatible Sun and Earth series lengths: {len(sun_series)} vs {len(earth_series)}"
        )
    for s_obs, e_obs in zip(sun_series, earth_series, strict=True):
        if s_obs.timestamp != e_obs.timestamp:
            raise HorizonsParseError(
                f"Incompatible Sun and Earth timestamps: {s_obs.timestamp} vs {e_obs.timestamp}"
            )

    horizon_elevation_deg = 0.0
    threshold = horizon_elevation_deg + visibility_margin_deg

    points: list[ObservationPoint] = []
    sun_flags: list[bool] = []
    earth_flags: list[bool] = []
    golden_flags: list[bool] = []

    for s_obs, e_obs in zip(sun_series, earth_series, strict=True):
        sun_enu = calculate_direction_enu(s_obs.azimuth_deg, s_obs.elevation_deg)
        earth_enu = calculate_direction_enu(e_obs.azimuth_deg, e_obs.elevation_deg)

        sun_vis = s_obs.elevation_deg > threshold
        earth_vis = e_obs.elevation_deg > threshold
        golden = sun_vis and earth_vis

        sun_flags.append(sun_vis)
        earth_flags.append(earth_vis)
        golden_flags.append(golden)

        points.append(
            ObservationPoint(
                timestamp=s_obs.timestamp,
                sun=BodyObservation(
                    azimuth_deg=s_obs.azimuth_deg,
                    elevation_deg=s_obs.elevation_deg,
                    horizon_elevation_deg=horizon_elevation_deg,
                    visible=sun_vis,
                    direction_enu=sun_enu,
                ),
                earth=BodyObservation(
                    azimuth_deg=e_obs.azimuth_deg,
                    elevation_deg=e_obs.elevation_deg,
                    horizon_elevation_deg=horizon_elevation_deg,
                    visible=earth_vis,
                    direction_enu=earth_enu,
                ),
                is_golden_window=golden,
            )
        )

    sunlight_windows = detect_continuous_windows(time_grid, sun_flags, step, dt_end)
    earth_visibility_windows = detect_continuous_windows(time_grid, earth_flags, step, dt_end)
    golden_windows = detect_continuous_windows(time_grid, golden_flags, step, dt_end)

    total_period_hours = (dt_end - dt_start).total_seconds() / 3600.0
    summary = calculate_timeline_summary(
        points=points,
        sunlight_windows=sunlight_windows,
        earth_visibility_windows=earth_visibility_windows,
        golden_windows=golden_windows,
        total_period_hours=total_period_hours,
    )

    sources = (
        [
            SourceMetadata(
                name=sun_series[0].provider_name,
                url=sun_series[0].source_url,
                version=sun_series[0].ephemeris_source,
                fetched_at=sun_series[0].retrieval_time,
                target="Sun",
                settings=sun_series[0].request_params,
            ),
            SourceMetadata(
                name=earth_series[0].provider_name,
                url=earth_series[0].source_url,
                version=earth_series[0].ephemeris_source,
                fetched_at=earth_series[0].retrieval_time,
                target="Earth",
                settings=earth_series[0].request_params,
            ),
        ]
        if sun_series and earth_series
        else []
    )

    return TimelineCalculationResult(
        start_time=dt_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_time=dt_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        step_minutes=step_minutes,
        total_samples=len(points),
        points=points,
        sunlight_windows=sunlight_windows,
        earth_visibility_windows=earth_visibility_windows,
        golden_windows=golden_windows,
        summary=summary,
        sources=sources,
    )


def calculate_terrain_timeline(
    *,
    latitude: float,
    longitude: float,
    start_time: datetime | str,
    duration_days: int,
    step_minutes: int,
    terrain_service: TerrainHorizonService,
    observer_height_m: float = 2.0,
    visibility_margin_deg: float = 0.0,
    provider: HorizonsProvider | None = None,
) -> TimelineCalculationResult:
    """Calculate multi-day terrain-aware observation timeline for Sun and Earth."""
    if not math.isfinite(latitude) or not -90.0 <= latitude <= 90.0:
        raise ValueError("Latitude must be a finite number between -90 and 90 degrees")

    if not math.isfinite(longitude) or not -180.0 <= longitude < 360.0:
        raise ValueError("Longitude must be a finite number in [-180, 360) degrees")

    if not math.isfinite(observer_height_m) or not 0.0 <= observer_height_m <= 20.0:
        raise ValueError("observer_height_m must be between 0 and 20 metres")

    if not math.isfinite(visibility_margin_deg) or not 0.0 <= visibility_margin_deg <= 5.0:
        raise ValueError("visibility_margin_deg must be between 0 and 5 degrees")

    time_grid = generate_time_grid(start_time, duration_days, step_minutes)
    dt_start = time_grid[0]
    dt_end = dt_start + timedelta(days=duration_days)
    step = timedelta(minutes=step_minutes)

    norm_lon = normalize_longitude(longitude)
    obs_surface = terrain_service.observer_surface
    actual_altitude_m = obs_surface.surface_elevation_m + observer_height_m

    active_provider = provider if provider is not None else HorizonsProvider()

    sun_series = active_provider.query_body_series(
        target="Sun",
        latitude=latitude,
        longitude=norm_lon,
        altitude_m=actual_altitude_m,
        start_time=dt_start,
        stop_time=dt_end,
        step_minutes=step_minutes,
    )
    earth_series = active_provider.query_body_series(
        target="Earth",
        latitude=latitude,
        longitude=norm_lon,
        altitude_m=actual_altitude_m,
        start_time=dt_start,
        stop_time=dt_end,
        step_minutes=step_minutes,
    )

    if len(sun_series) != len(earth_series):
        raise HorizonsParseError(
            f"Incompatible Sun and Earth series lengths: {len(sun_series)} vs {len(earth_series)}"
        )
    for s_obs, e_obs in zip(sun_series, earth_series, strict=True):
        if s_obs.timestamp != e_obs.timestamp:
            raise HorizonsParseError(
                f"Incompatible Sun and Earth timestamps: {s_obs.timestamp} vs {e_obs.timestamp}"
            )

    points: list[ObservationPoint] = []
    sun_flags: list[bool] = []
    earth_flags: list[bool] = []
    golden_flags: list[bool] = []

    horizon_cache: dict[float, HorizonResult] = {}

    def _get_horizon(az_deg: float) -> HorizonResult:
        key = round(az_deg % 360.0, 6)
        if key not in horizon_cache:
            horizon_cache[key] = terrain_service.horizon_elevation(az_deg)
        return horizon_cache[key]

    for s_obs, e_obs in zip(sun_series, earth_series, strict=True):
        sun_enu = calculate_direction_enu(s_obs.azimuth_deg, s_obs.elevation_deg)
        earth_enu = calculate_direction_enu(e_obs.azimuth_deg, e_obs.elevation_deg)

        sun_horizon = _get_horizon(s_obs.azimuth_deg)
        earth_horizon = _get_horizon(e_obs.azimuth_deg)

        sun_horizon_deg = sun_horizon.horizon_elevation_deg
        earth_horizon_deg = earth_horizon.horizon_elevation_deg

        sun_vis = s_obs.elevation_deg > (sun_horizon_deg + visibility_margin_deg)
        earth_vis = e_obs.elevation_deg > (earth_horizon_deg + visibility_margin_deg)
        golden = sun_vis and earth_vis

        sun_flags.append(sun_vis)
        earth_flags.append(earth_vis)
        golden_flags.append(golden)

        points.append(
            ObservationPoint(
                timestamp=s_obs.timestamp,
                sun=BodyObservation(
                    azimuth_deg=s_obs.azimuth_deg,
                    elevation_deg=s_obs.elevation_deg,
                    horizon_elevation_deg=sun_horizon_deg,
                    visible=sun_vis,
                    direction_enu=sun_enu,
                ),
                earth=BodyObservation(
                    azimuth_deg=e_obs.azimuth_deg,
                    elevation_deg=e_obs.elevation_deg,
                    horizon_elevation_deg=earth_horizon_deg,
                    visible=earth_vis,
                    direction_enu=earth_enu,
                ),
                is_golden_window=golden,
                surface_elevation_m=obs_surface.surface_elevation_m,
                terrain_dataset_id=obs_surface.dataset_id,
            )
        )

    sunlight_windows = detect_continuous_windows(time_grid, sun_flags, step, dt_end)
    earth_visibility_windows = detect_continuous_windows(time_grid, earth_flags, step, dt_end)
    golden_windows = detect_continuous_windows(time_grid, golden_flags, step, dt_end)

    total_period_hours = (dt_end - dt_start).total_seconds() / 3600.0
    summary = calculate_timeline_summary(
        points=points,
        sunlight_windows=sunlight_windows,
        earth_visibility_windows=earth_visibility_windows,
        golden_windows=golden_windows,
        total_period_hours=total_period_hours,
    )

    sources = (
        [
            SourceMetadata(
                name=sun_series[0].provider_name,
                url=sun_series[0].source_url,
                version=sun_series[0].ephemeris_source,
                fetched_at=sun_series[0].retrieval_time,
                target="Sun",
                settings=sun_series[0].request_params,
            ),
            SourceMetadata(
                name=earth_series[0].provider_name,
                url=earth_series[0].source_url,
                version=earth_series[0].ephemeris_source,
                fetched_at=earth_series[0].retrieval_time,
                target="Earth",
                settings=earth_series[0].request_params,
            ),
        ]
        if sun_series and earth_series
        else []
    )

    return TimelineCalculationResult(
        start_time=dt_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_time=dt_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        step_minutes=step_minutes,
        total_samples=len(points),
        points=points,
        sunlight_windows=sunlight_windows,
        earth_visibility_windows=earth_visibility_windows,
        golden_windows=golden_windows,
        summary=summary,
        sources=sources,
        surface_elevation_m=obs_surface.surface_elevation_m,
        terrain_dataset_id=obs_surface.dataset_id,
    )


def calculate_timeline(
    *,
    latitude: float,
    longitude: float,
    start_time: datetime | str,
    duration_days: int,
    step_minutes: int,
    horizon_mode: Literal["geometric", "terrain"] = "geometric",
    terrain_service: TerrainHorizonService | None = None,
    observer_height_m: float = 2.0,
    visibility_margin_deg: float = 0.0,
    provider: HorizonsProvider | None = None,
) -> TimelineCalculationResult:
    """Calculate multi-day timeline supporting both geometric and terrain modes."""
    if horizon_mode == "geometric":
        return calculate_geometric_timeline(
            latitude=latitude,
            longitude=longitude,
            start_time=start_time,
            duration_days=duration_days,
            step_minutes=step_minutes,
            observer_height_m=observer_height_m,
            visibility_margin_deg=visibility_margin_deg,
            provider=provider,
        )
    elif horizon_mode == "terrain":
        if terrain_service is None:
            raise ValueError("terrain_service is required when horizon_mode is 'terrain'")
        return calculate_terrain_timeline(
            latitude=latitude,
            longitude=longitude,
            start_time=start_time,
            duration_days=duration_days,
            step_minutes=step_minutes,
            terrain_service=terrain_service,
            observer_height_m=observer_height_m,
            visibility_margin_deg=visibility_margin_deg,
            provider=provider,
        )
    else:
        raise ValueError(f"Unsupported horizon_mode '{horizon_mode}'")
