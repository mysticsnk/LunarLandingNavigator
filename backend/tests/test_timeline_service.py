"""Tests for Stage 3 geometric timeline astronomy calculation service.

Covers time grid generation, Horizons time-series query validation,
continuous visibility window detection, aggregate summary metrics,
and consistency with single-instant geometric observations.
"""

from __future__ import annotations

import json
import math
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app.astronomy.horizons import (
    HorizonsParseError,
    HorizonsProvider,
    HorizonsProviderError,
)
from app.astronomy.observation import (
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

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "contracts"


def test_time_grid_respects_half_open_period_and_step_counts():
    """Verify exact time grid [start_time, end_time) excluding end_time."""
    start_time = "2027-07-01T00:00:00Z"

    # 30 days at 60-minute steps produces exactly 720 points
    grid_30d_60m = generate_time_grid(start_time, duration_days=30, step_minutes=60)
    assert len(grid_30d_60m) == 720
    assert grid_30d_60m[0] == datetime(2027, 7, 1, 0, 0, tzinfo=UTC)
    assert grid_30d_60m[-1] == datetime(2027, 7, 30, 23, 0, tzinfo=UTC)
    assert datetime(2027, 7, 31, 0, 0, tzinfo=UTC) not in grid_30d_60m

    # 14 days at 120-minute steps produces exactly 168 points
    grid_14d_120m = generate_time_grid(start_time, duration_days=14, step_minutes=120)
    assert len(grid_14d_120m) == 168
    assert grid_14d_120m[0] == datetime(2027, 7, 1, 0, 0, tzinfo=UTC)
    assert grid_14d_120m[-1] == datetime(2027, 7, 14, 22, 0, tzinfo=UTC)
    assert datetime(2027, 7, 15, 0, 0, tzinfo=UTC) not in grid_14d_120m

    # All timestamps must be timezone-aware UTC
    for ts in grid_14d_120m:
        assert ts.tzinfo == UTC


def test_time_grid_validates_inputs_strictly():
    """Verify strict input validation on duration, steps, timezone, and range."""
    # Duration bounds: 1 to 30 days
    with pytest.raises(ValueError, match="duration_days"):
        generate_time_grid("2027-07-01T00:00:00Z", duration_days=0, step_minutes=60)
    with pytest.raises(ValueError, match="duration_days"):
        generate_time_grid("2027-07-01T00:00:00Z", duration_days=31, step_minutes=60)

    # Allowed step minutes
    for step in ALLOWED_STEP_MINUTES:
        assert len(generate_time_grid("2027-07-01T00:00:00Z", 1, step)) == 1440 // step

    with pytest.raises(ValueError, match="step_minutes"):
        generate_time_grid("2027-07-01T00:00:00Z", duration_days=1, step_minutes=45)

    # Naive timestamp without timezone
    with pytest.raises(ValueError, match="timezone"):
        generate_time_grid("2027-07-01T00:00:00", duration_days=1, step_minutes=60)

    # Exceeding supported maximum range 2050-01-01
    with pytest.raises(ValueError, match="exceed"):
        generate_time_grid("2049-12-20T00:00:00Z", duration_days=20, step_minutes=60)


def test_continuous_windows_handles_all_required_topologies():
    """Verify window merging and splitting across various topological edge cases."""
    start = datetime(2027, 7, 1, 0, 0, tzinfo=UTC)
    step = timedelta(minutes=60)
    timestamps = [start + i * step for i in range(4)]
    end_time = start + timedelta(hours=4)

    # Case 1: All False -> empty windows
    w_false = detect_continuous_windows(timestamps, [False, False, False, False], step, end_time)
    assert w_false == []

    # Case 2: All True -> single merged window spanning entire period
    w_true = detect_continuous_windows(timestamps, [True, True, True, True], step, end_time)
    assert len(w_true) == 1
    assert w_true[0].start_time == "2027-07-01T00:00:00Z"
    assert w_true[0].end_time == "2027-07-01T04:00:00Z"
    assert w_true[0].duration_hours == 4.0

    # Case 3: First sample True only -> one-sample window at start
    w_first = detect_continuous_windows(timestamps, [True, False, False, False], step, end_time)
    assert len(w_first) == 1
    assert w_first[0].start_time == "2027-07-01T00:00:00Z"
    assert w_first[0].end_time == "2027-07-01T01:00:00Z"
    assert w_first[0].duration_hours == 1.0

    # Case 4: Last sample True only -> one-sample window at end
    w_last = detect_continuous_windows(timestamps, [False, False, False, True], step, end_time)
    assert len(w_last) == 1
    assert w_last[0].start_time == "2027-07-01T03:00:00Z"
    assert w_last[0].end_time == "2027-07-01T04:00:00Z"
    assert w_last[0].duration_hours == 1.0

    # Case 5: Single sample True in the middle
    w_mid = detect_continuous_windows(timestamps, [False, True, False, False], step, end_time)
    assert len(w_mid) == 1
    assert w_mid[0].start_time == "2027-07-01T01:00:00Z"
    assert w_mid[0].end_time == "2027-07-01T02:00:00Z"
    assert w_mid[0].duration_hours == 1.0

    # Case 6: Multiple separate windows
    w_multi = detect_continuous_windows(timestamps, [True, False, True, True], step, end_time)
    assert len(w_multi) == 2
    assert w_multi[0].start_time == "2027-07-01T00:00:00Z"
    assert w_multi[0].end_time == "2027-07-01T01:00:00Z"
    assert w_multi[0].duration_hours == 1.0
    assert w_multi[1].start_time == "2027-07-01T02:00:00Z"
    assert w_multi[1].end_time == "2027-07-01T04:00:00Z"
    assert w_multi[1].duration_hours == 2.0


def test_windows_separated_by_gap_are_never_merged():
    """Regression test: verify that two favorable intervals separated by a gap are never merged."""
    start = datetime(2027, 7, 1, 0, 0, tzinfo=UTC)
    step = timedelta(minutes=60)
    timestamps = [start + i * step for i in range(6)]
    end_time = start + timedelta(hours=6)

    # Pattern: True, True, False, False, True, False
    flags = [True, True, False, False, True, False]
    windows = detect_continuous_windows(timestamps, flags, step, end_time)

    assert len(windows) == 2
    # First window: [00:00, 02:00), 2 hours
    assert windows[0].start_time == "2027-07-01T00:00:00Z"
    assert windows[0].end_time == "2027-07-01T02:00:00Z"
    assert windows[0].duration_hours == 2.0

    # Second window: [04:00, 05:00), 1 hour
    assert windows[1].start_time == "2027-07-01T04:00:00Z"
    assert windows[1].end_time == "2027-07-01T05:00:00Z"
    assert windows[1].duration_hours == 1.0

    # Gap between 02:00 and 04:00 is strictly preserved
    assert windows[0].end_time != windows[1].start_time


def test_summary_metrics_reproduce_contract_example():
    """Verify summary metrics calculation against canonical timeline fixture."""
    fixture_path = CONTRACTS_DIR / "examples" / "timeline-two-golden-windows.json"
    with open(fixture_path, encoding="utf-8") as f:
        fixture_data = json.load(f)

    from app.astronomy.observation import BodyObservation, DirectionENU, ObservationPoint

    points = [
        ObservationPoint(
            timestamp=p["timestamp"],
            sun=BodyObservation(
                azimuth_deg=p["sun"]["azimuth_deg"],
                elevation_deg=p["sun"]["elevation_deg"],
                horizon_elevation_deg=p["sun"]["horizon_elevation_deg"],
                visible=p["sun"]["visible"],
                direction_enu=DirectionENU(**p["sun"]["direction_enu"]),
            ),
            earth=BodyObservation(
                azimuth_deg=p["earth"]["azimuth_deg"],
                elevation_deg=p["earth"]["elevation_deg"],
                horizon_elevation_deg=p["earth"]["horizon_elevation_deg"],
                visible=p["earth"]["visible"],
                direction_enu=DirectionENU(**p["earth"]["direction_enu"]),
            ),
            is_golden_window=p["is_golden_window"],
        )
        for p in fixture_data["points"]
    ]

    sun_windows = [Window(**w) for w in fixture_data["sunlight_windows"]]
    earth_windows = [Window(**w) for w in fixture_data["earth_visibility_windows"]]
    golden_windows = [Window(**w) for w in fixture_data["golden_windows"]]

    summary = calculate_timeline_summary(
        points=points,
        sunlight_windows=sun_windows,
        earth_visibility_windows=earth_windows,
        golden_windows=golden_windows,
        total_period_hours=24.0,
    )

    expected = fixture_data["summary"]
    assert summary.sunlit_hours == expected["sunlit_hours"]
    assert summary.sunlit_pct == expected["sunlit_pct"]
    assert summary.earth_visible_hours == expected["earth_visible_hours"]
    assert summary.earth_visible_pct == expected["earth_visible_pct"]
    assert summary.golden_hours == expected["golden_hours"]
    assert summary.golden_pct == expected["golden_pct"]
    assert summary.longest_golden_window_hours == expected["longest_golden_window_hours"]
    assert summary.average_sun_elevation_deg == expected["average_sun_elevation_deg"]
    assert summary.next_sunset_at == expected["next_sunset_at"]
    assert summary.next_earthset_at == expected["next_earthset_at"]


def test_sunset_and_earthset_require_physical_transition():
    """Verify that sunset and earthset are only recorded on True->False transitions."""
    from app.astronomy.observation import BodyObservation, DirectionENU, ObservationPoint

    def make_point(ts: str, sun_vis: bool, earth_vis: bool) -> ObservationPoint:
        enu = DirectionENU(east=0.0, north=1.0, up=0.0)
        return ObservationPoint(
            timestamp=ts,
            sun=BodyObservation(
                azimuth_deg=0.0,
                elevation_deg=10.0 if sun_vis else -10.0,
                horizon_elevation_deg=0.0,
                visible=sun_vis,
                direction_enu=enu,
            ),
            earth=BodyObservation(
                azimuth_deg=0.0,
                elevation_deg=10.0 if earth_vis else -10.0,
                horizon_elevation_deg=0.0,
                visible=earth_vis,
                direction_enu=enu,
            ),
            is_golden_window=sun_vis and earth_vis,
        )

    # Case 1: Always visible -> no transition -> next_sunset_at is None
    points_always_vis = [
        make_point("2027-07-01T00:00:00Z", True, True),
        make_point("2027-07-01T01:00:00Z", True, True),
        make_point("2027-07-01T02:00:00Z", True, True),
    ]
    summary1 = calculate_timeline_summary(
        points=points_always_vis,
        sunlight_windows=[
            Window(
                start_time="2027-07-01T00:00:00Z",
                end_time="2027-07-01T03:00:00Z",
                duration_hours=3.0,
            )
        ],
        earth_visibility_windows=[],
        golden_windows=[],
        total_period_hours=3.0,
    )
    assert summary1.next_sunset_at is None
    assert summary1.next_earthset_at is None

    # Case 2: Visible then Invisible -> transition at the invisible sample
    points_transition = [
        make_point("2027-07-01T00:00:00Z", True, False),
        make_point("2027-07-01T01:00:00Z", False, True),
        make_point("2027-07-01T02:00:00Z", False, False),
    ]
    summary2 = calculate_timeline_summary(
        points=points_transition,
        sunlight_windows=[],
        earth_visibility_windows=[],
        golden_windows=[],
        total_period_hours=3.0,
    )
    assert summary2.next_sunset_at == "2027-07-01T01:00:00Z"
    assert summary2.next_earthset_at == "2027-07-01T02:00:00Z"

    # Case 3: Invisible then Visible (sunrise/earthrise) -> NOT a set event
    points_rise = [
        make_point("2027-07-01T00:00:00Z", False, False),
        make_point("2027-07-01T01:00:00Z", True, True),
    ]
    summary3 = calculate_timeline_summary(
        points=points_rise,
        sunlight_windows=[],
        earth_visibility_windows=[],
        golden_windows=[],
        total_period_hours=2.0,
    )
    assert summary3.next_sunset_at is None
    assert summary3.next_earthset_at is None


def _make_mock_series_response(
    start_dt: datetime,
    step_minutes: int,
    count: int,
    include_endpoint: bool = True,
    corrupt_row: int | None = None,
    duplicate_row: bool = False,
    missing_row: int | None = None,
) -> dict:
    lines = []
    total = count + (1 if include_endpoint else 0)
    for i in range(total):
        if missing_row is not None and i == missing_row:
            continue
        dt = start_dt + i * timedelta(minutes=step_minutes)
        dt_str = dt.strftime("%Y-%b-%d %H:%M:%S")
        if corrupt_row is not None and i == corrupt_row:
            lines.append(f" {dt_str},*,i,  n.a.,    n.a.,")
        else:
            lines.append(f" {dt_str},*,i,  120.000000,    10.000000,")
        if duplicate_row and i == 0:
            lines.append(f" {dt_str},*,i,  120.000000,    10.000000,")

    text = "$$SOE\n" + "\n".join(lines) + "\n$$EOE"
    return {
        "result": text,
        "signature": {"source": "NASA/JPL Horizons API", "version": "1.2"},
    }


def test_horizons_provider_filters_endpoint_row_correctly():
    """Verify that HorizonsProvider filters endpoint rows and validates row count."""
    start_dt = datetime(2027, 7, 1, 0, 0, tzinfo=UTC)
    stop_dt = datetime(2027, 7, 1, 6, 0, tzinfo=UTC)

    # 3 samples: 00:00, 02:00, 04:00; plus endpoint 06:00
    mock_data = _make_mock_series_response(
        start_dt, step_minutes=120, count=3, include_endpoint=True
    )

    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=mock_data))
    with httpx.Client(transport=transport) as client:
        provider = HorizonsProvider(client=client)
        series = provider.query_body_series(
            target="Sun",
            latitude=-89.44,
            longitude=-137.9,
            start_time=start_dt,
            stop_time=stop_dt,
            step_minutes=120,
        )

    assert len(series) == 3
    assert series[0].timestamp == "2027-07-01T00:00:00Z"
    assert series[1].timestamp == "2027-07-01T02:00:00Z"
    assert series[2].timestamp == "2027-07-01T04:00:00Z"


def test_horizons_provider_rejects_duplicates_gaps_and_corrupt_data():
    """Verify robust rejection of malformed or inconsistent provider responses."""
    start_dt = datetime(2027, 7, 1, 0, 0, tzinfo=UTC)
    stop_dt = datetime(2027, 7, 1, 6, 0, tzinfo=UTC)

    # 1. Duplicate timestamp
    dup_data = _make_mock_series_response(start_dt, 120, 3, duplicate_row=True)
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=dup_data))
    ) as client:
        provider = HorizonsProvider(client=client)
        with pytest.raises(HorizonsParseError, match="Duplicate"):
            provider.query_body_series(
                target="Sun",
                latitude=0,
                longitude=0,
                start_time=start_dt,
                stop_time=stop_dt,
                step_minutes=120,
            )

    # 2. Missing timestamp / gap
    missing_data = _make_mock_series_response(start_dt, 120, 3, missing_row=1)
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=missing_data))
    ) as client:
        provider = HorizonsProvider(client=client)
        with pytest.raises(HorizonsParseError, match="missing"):
            provider.query_body_series(
                target="Sun",
                latitude=0,
                longitude=0,
                start_time=start_dt,
                stop_time=stop_dt,
                step_minutes=120,
            )

    # 3. Corrupt / n.a. numeric value
    corrupt_data = _make_mock_series_response(start_dt, 120, 3, corrupt_row=1)
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=corrupt_data))
    ) as client:
        provider = HorizonsProvider(client=client)
        with pytest.raises(HorizonsParseError, match="missing"):
            provider.query_body_series(
                target="Sun",
                latitude=0,
                longitude=0,
                start_time=start_dt,
                stop_time=stop_dt,
                step_minutes=120,
            )

    # 4. Provider error inside 200 JSON
    error_data = {"error": "Invalid target specified"}
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=error_data))
    ) as client:
        provider = HorizonsProvider(client=client)
        with pytest.raises(HorizonsProviderError, match="Invalid target"):
            provider.query_body_series(
                target="Sun",
                latitude=0,
                longitude=0,
                start_time=start_dt,
                stop_time=stop_dt,
                step_minutes=120,
            )


def test_calculate_geometric_timeline_agrees_with_single_observation():
    """Verify that points produced by timeline service match single observation calculation."""
    start_dt = datetime(2027, 7, 15, 12, 0, tzinfo=UTC)

    # We mock responses for Sun and Earth for 1 day at 360m (4 points)
    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(httpx.QueryParams(request.url.query))
        target_cmd = params.get("COMMAND", "").replace("'", "")
        # Return elevated for Sun and Earth at 12:00
        step_minutes = 360
        count = 4
        lines = []
        for i in range(count + 1):
            dt = start_dt + i * timedelta(minutes=step_minutes)
            dt_str = dt.strftime("%Y-%b-%d %H:%M:%S")
            # If Earth, use azimuth 140, elev 5.0; if Sun, use azimuth 180, elev 2.0
            if target_cmd == "10":
                lines.append(f" {dt_str},*,i,  180.000000,    2.000000,")
            else:
                lines.append(f" {dt_str},*,i,  140.000000,    5.000000,")

        text = "$$SOE\n" + "\n".join(lines) + "\n$$EOE"
        return httpx.Response(
            200,
            json={"result": text, "signature": {"source": "NASA/JPL Horizons API"}},
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        provider = HorizonsProvider(client=client)

        timeline_res = calculate_geometric_timeline(
            latitude=-89.44,
            longitude=-137.9,
            start_time=start_dt,
            duration_days=1,
            step_minutes=360,
            observer_height_m=5.0,
            visibility_margin_deg=1.5,
            provider=provider,
        )

        single_res = calculate_geometric_observation(
            latitude=-89.44,
            longitude=-137.9,
            target_time=start_dt,
            observer_height_m=5.0,
            visibility_margin_deg=1.5,
            provider=provider,
        )

    assert timeline_res.total_samples == 4
    point0 = timeline_res.points[0]

    # Compare angles and visibility
    assert math.isclose(point0.sun.azimuth_deg, single_res.sun.azimuth_deg)
    assert math.isclose(point0.sun.elevation_deg, single_res.sun.elevation_deg)
    assert point0.sun.visible == single_res.sun.visible

    assert math.isclose(point0.earth.azimuth_deg, single_res.earth.azimuth_deg)
    assert math.isclose(point0.earth.elevation_deg, single_res.earth.elevation_deg)
    assert point0.earth.visible == single_res.earth.visible

    assert point0.is_golden_window == single_res.is_golden_window

    # ENU vectors must match
    assert math.isclose(point0.sun.direction_enu.east, single_res.sun.direction_enu.east)
    assert math.isclose(point0.sun.direction_enu.north, single_res.sun.direction_enu.north)
    assert math.isclose(point0.sun.direction_enu.up, single_res.sun.direction_enu.up)


@pytest.mark.skipif(
    not os.getenv("TEST_LIVE_HORIZONS"),
    reason="Set TEST_LIVE_HORIZONS to run live JPL Horizons timeline query",
)
def test_live_horizons_timeline_query():
    """Live integration check against actual JPL Horizons API."""
    provider = HorizonsProvider(timeout=20.0)
    result = calculate_geometric_timeline(
        latitude=-89.44,
        longitude=-137.9,
        start_time="2027-07-15T00:00:00Z",
        duration_days=1,
        step_minutes=360,
        provider=provider,
    )

    assert result.total_samples == 4
    assert len(result.points) == 4
    assert result.summary.sunlit_hours >= 0.0
    assert 0.0 <= result.summary.sunlit_pct <= 100.0
    assert len(result.sources) == 2
