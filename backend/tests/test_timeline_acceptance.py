"""Independent Stage 3 acceptance checks against controlled timeline states."""

from __future__ import annotations

import json
import math
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from app.astronomy.horizons import HorizonsProvider
from app.astronomy.observation import (
    BodyObservation,
    ObservationPoint,
    calculate_direction_enu,
    calculate_geometric_observation,
)
from app.astronomy.timeline import (
    ALLOWED_STEP_MINUTES,
    Window,
    calculate_geometric_timeline,
    calculate_timeline_summary,
    detect_continuous_windows,
    generate_time_grid,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "timeline_acceptance.json"


@pytest.fixture(scope="module")
def fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _offset_windows(start: datetime, offsets: list[list[int]]) -> list[Window]:
    return [
        Window(
            start_time=(start + timedelta(hours=begin)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            end_time=(start + timedelta(hours=end)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            duration_hours=end - begin,
        )
        for begin, end in offsets
    ]


def _window_rows(windows: list[Window]) -> list[tuple[str, str, float]]:
    return [(window.start_time, window.end_time, window.duration_hours) for window in windows]


def _points(
    start: datetime,
    offsets: list[int],
    sun_flags: list[bool],
    earth_flags: list[bool],
) -> list[ObservationPoint]:
    points = []
    for offset, sun_visible, earth_visible in zip(offsets, sun_flags, earth_flags, strict=True):
        sun_elevation = 1.0 if sun_visible else -1.0
        earth_elevation = 1.0 if earth_visible else -1.0
        points.append(
            ObservationPoint(
                timestamp=(start + timedelta(hours=offset)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                sun=BodyObservation(
                    azimuth_deg=0.0,
                    elevation_deg=sun_elevation,
                    horizon_elevation_deg=0.0,
                    visible=sun_visible,
                    direction_enu=calculate_direction_enu(0.0, sun_elevation),
                ),
                earth=BodyObservation(
                    azimuth_deg=0.0,
                    elevation_deg=earth_elevation,
                    horizon_elevation_deg=0.0,
                    visible=earth_visible,
                    direction_enu=calculate_direction_enu(0.0, earth_elevation),
                ),
                is_golden_window=sun_visible and earth_visible,
            )
        )
    return points


@pytest.mark.parametrize("case_index", range(5))
def test_explicit_golden_window_topologies(fixture, case_index):
    case = fixture["topology_cases"][case_index]
    start = _time(fixture["start_time"])
    timestamps = [start + timedelta(hours=offset) for offset in fixture["sample_offsets_hours"]]
    end = _time(fixture["end_time"])
    actual = detect_continuous_windows(
        timestamps,
        case["states"],
        timedelta(hours=fixture["step_hours"]),
        end,
    )
    expected = _offset_windows(start, case["windows_offsets_hours"])
    assert _window_rows(actual) == _window_rows(expected), case["name"]

    points = _points(
        start,
        fixture["sample_offsets_hours"],
        case["states"],
        case["states"],
    )
    summary = calculate_timeline_summary(
        points=points,
        sunlight_windows=actual,
        earth_visibility_windows=actual,
        golden_windows=actual,
        total_period_hours=12,
    )
    assert summary.golden_hours == case["golden_hours"]
    assert summary.longest_golden_window_hours == case["longest_golden_window_hours"]


def test_twelve_hour_two_hour_acceptance_case_and_metric_consistency(fixture):
    case = fixture["golden_case"]
    start = _time(fixture["start_time"])
    end = _time(fixture["end_time"])
    step = timedelta(hours=fixture["step_hours"])
    timestamps = [start + timedelta(hours=offset) for offset in fixture["sample_offsets_hours"]]
    points = _points(
        start,
        fixture["sample_offsets_hours"],
        case["sun_visible"],
        case["earth_visible"],
    )
    sun_windows = detect_continuous_windows(timestamps, case["sun_visible"], step, end)
    earth_windows = detect_continuous_windows(timestamps, case["earth_visible"], step, end)
    golden_windows = detect_continuous_windows(timestamps, case["golden_states"], step, end)

    assert [point.timestamp for point in points] == sorted(point.timestamp for point in points)
    assert points[-1].timestamp != fixture["end_time"]
    assert _window_rows(golden_windows) == _window_rows(
        _offset_windows(start, case["golden_windows_offsets_hours"])
    )

    summary = calculate_timeline_summary(
        points=points,
        sunlight_windows=sun_windows,
        earth_visibility_windows=earth_windows,
        golden_windows=golden_windows,
        total_period_hours=(end - start).total_seconds() / 3600,
    )
    assert summary.sunlit_hours == case["sunlit_hours"]
    assert summary.earth_visible_hours == case["earth_visible_hours"]
    assert summary.golden_hours == case["golden_hours"] == 8
    assert summary.longest_golden_window_hours == case["longest_golden_window_hours"] == 4
    assert summary.sunlit_pct == pytest.approx(100 * 10 / 12)
    assert summary.earth_visible_pct == pytest.approx(100 * 10 / 12)
    assert summary.golden_pct == pytest.approx(100 * 8 / 12)
    assert all(
        0 <= pct <= 100
        for pct in (summary.sunlit_pct, summary.earth_visible_pct, summary.golden_pct)
    )

    for windows, hours in (
        (sun_windows, summary.sunlit_hours),
        (earth_windows, summary.earth_visible_hours),
        (golden_windows, summary.golden_hours),
    ):
        assert sum(window.duration_hours for window in windows) == hours
        assert hours <= (end - start).total_seconds() / 3600
        assert all(
            (_time(window.end_time) - _time(window.start_time)).total_seconds() / 3600
            == window.duration_hours
            for window in windows
        )
        assert all(
            _time(left.end_time) <= _time(right.start_time)
            for left, right in zip(windows, windows[1:], strict=False)
        )

    assert summary.longest_golden_window_hours == max(
        window.duration_hours for window in golden_windows
    )
    assert all(
        point.is_golden_window == (point.sun.visible and point.earth.visible) for point in points
    )


def test_distinct_sun_and_earth_sequences_only_form_simultaneous_golden_intervals(fixture):
    case = fixture["different_body_sequences"]
    start = _time(fixture["start_time"])
    timestamps = [start + timedelta(hours=offset) for offset in fixture["sample_offsets_hours"]]
    step = timedelta(hours=fixture["step_hours"])
    end = _time(fixture["end_time"])
    points = _points(
        start,
        fixture["sample_offsets_hours"],
        case["sun_visible"],
        case["earth_visible"],
    )

    assert [point.is_golden_window for point in points] == case["golden_states"]
    for flags, expected_key in (
        (case["sun_visible"], "sunlight_windows_offsets_hours"),
        (case["earth_visible"], "earth_windows_offsets_hours"),
        (case["golden_states"], "golden_windows_offsets_hours"),
    ):
        actual = detect_continuous_windows(timestamps, flags, step, end)
        assert _window_rows(actual) == _window_rows(_offset_windows(start, case[expected_key]))


def test_final_interval_is_clipped_without_inventing_set_events(fixture):
    start = _time(fixture["start_time"])
    end = _time(fixture["end_time"])
    offsets = fixture["sample_offsets_hours"]
    flags = [True] * len(offsets)
    timestamps = [start + timedelta(hours=offset) for offset in offsets]
    windows = detect_continuous_windows(
        timestamps, flags, timedelta(hours=fixture["step_hours"]), end
    )
    summary = calculate_timeline_summary(
        points=_points(start, offsets, flags, flags),
        sunlight_windows=windows,
        earth_visibility_windows=windows,
        golden_windows=windows,
        total_period_hours=12,
    )

    assert _window_rows(windows) == _window_rows(_offset_windows(start, [[0, 12]]))
    assert windows[0].end_time == fixture["end_time"]
    assert summary.next_sunset_at is None
    assert summary.next_earthset_at is None


def test_missing_sample_is_a_gap_not_a_bridge(fixture):
    start = _time(fixture["start_time"])
    timestamps = [start + timedelta(hours=value) for value in [0, 2, 6, 8, 10]]
    windows = detect_continuous_windows(
        timestamps,
        [True] * len(timestamps),
        timedelta(hours=fixture["step_hours"]),
        _time(fixture["end_time"]),
    )
    assert _window_rows(windows) == _window_rows(_offset_windows(start, [[0, 4], [6, 12]]))


def test_all_allowed_step_sizes_have_chronological_half_open_grids():
    for step_minutes in ALLOWED_STEP_MINUTES:
        grid = generate_time_grid("2027-07-01T00:00:00Z", 1, step_minutes)
        end = datetime(2027, 7, 2, tzinfo=UTC)
        step = timedelta(minutes=step_minutes)
        assert len(grid) == 1440 // step_minutes
        assert grid == sorted(grid)
        assert grid[0] == datetime(2027, 7, 1, tzinfo=UTC)
        assert grid[-1] + step == end
        assert end not in grid


def test_controlled_contract_fixture_matches_openapi_timeline_result_schema():
    contract = yaml.safe_load((ROOT / "contracts" / "openapi.v1.yaml").read_text(encoding="utf-8"))
    response = json.loads(
        (ROOT / "contracts" / "examples" / "timeline-two-golden-windows.json").read_text(
            encoding="utf-8"
        )
    )
    schema = {"$ref": "#/components/schemas/TimelineResult", "components": contract["components"]}
    Draft202012Validator(schema).validate(response)


@pytest.mark.skipif(
    not os.getenv("TEST_LIVE_HORIZONS"),
    reason="Set TEST_LIVE_HORIZONS to compare a live timeline sample with a single observation",
)
def test_live_timeline_sample_matches_single_observation():
    provider = HorizonsProvider(timeout=12.0, max_retries=0)
    start = "2027-07-15T00:00:00Z"
    timeline = calculate_geometric_timeline(
        latitude=-89.44,
        longitude=-137.9,
        start_time=start,
        duration_days=1,
        step_minutes=360,
        provider=provider,
    )
    single = calculate_geometric_observation(
        latitude=-89.44,
        longitude=-137.9,
        target_time=start,
        provider=provider,
    )

    sample = timeline.points[0]
    assert sample.timestamp == single.timestamp
    assert sample.sun.visible == single.sun.visible
    assert sample.earth.visible == single.earth.visible
    assert sample.is_golden_window == single.is_golden_window
    assert math.isclose(sample.sun.azimuth_deg, single.sun.azimuth_deg, abs_tol=1e-6)
    assert math.isclose(sample.sun.elevation_deg, single.sun.elevation_deg, abs_tol=1e-6)
    assert math.isclose(sample.earth.azimuth_deg, single.earth.azimuth_deg, abs_tol=1e-6)
    assert math.isclose(sample.earth.elevation_deg, single.earth.elevation_deg, abs_tol=1e-6)
