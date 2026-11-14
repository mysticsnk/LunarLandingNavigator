# Stage 3 Astronomy & Timeline Validation Report

This document records the design, implementation, and verification of the Stage 3
astronomical timeline service for the Lunar Landing Site Navigator.

## 1. Scope & System Roles

- **Assigned Area:** Astronomy provider time-range queries, multi-day geometric timeline
  calculation, continuous visibility window detection, and aggregate summary metrics.
- **Consumers & Handoffs:**
  - **Yaroslav (Backend / Worker):** Calls `calculate_geometric_timeline` in the timeline job
    execution worker and maps `TimelineCalculationResult` into OpenAPI `TimelineResult`.
  - **Sasha (Frontend / Workflows):** Visualizes timeline observation points, continuous
    sunlight/Earth/golden windows, and period summary metrics.
  - **Slavik (3D Scene / Visuals):** Drives the local 3D observer view and sun/earth trajectory
    using the validated per-point unit ENU direction vectors and visibility flags.

## 2. Service Interface

The service is exported from `app.astronomy`:

```python
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
    ...
```

### Models

- `Window`: `start_time: str`, `end_time: str`, `duration_hours: float` (strictly `> 0.0`).
- `Summary`:
  - `sunlit_hours`, `sunlit_pct`
  - `earth_visible_hours`, `earth_visible_pct`
  - `golden_hours`, `golden_pct`
  - `longest_golden_window_hours` (defaults to `0.0` when no golden window exists)
  - `average_sun_elevation_deg` (sample average across points)
  - `next_sunset_at`: ISO timestamp of the first observed `True -> False` transition, or `None`
  - `next_earthset_at`: ISO timestamp of the first observed `True -> False` transition, or `None`
- `TimelineCalculationResult`:
  - `start_time: str`, `end_time: str`
  - `step_minutes: int`, `total_samples: int`
  - `points: list[ObservationPoint]`
  - `sunlight_windows: list[Window]`
  - `earth_visibility_windows: list[Window]`
  - `golden_windows: list[Window]`
  - `summary: Summary`
  - `sources: list[SourceMetadata]` (excluded from direct serialization, available for `meta.sources`)

## 3. Scientific Rules & Invariants

1. **Time Grid Invariant:**
   - Calculation period is half-open `[start_time, end_time)`.
   - The sample at `end_time` is **never** included.
   - Total sample count: $N = \text{duration\_days} \times 1440 / \text{step\_minutes}$.
   - Verified benchmarks: 30 days at 60m produces 720 samples; 14 days at 120m produces 168 samples.
2. **Horizons Ephemeris Integration:**
   - Provider queried using bounded `START_TIME`, `STOP_TIME`, and `STEP_SIZE` (`f"{step_minutes}m"`).
   - If Horizons includes a boundary endpoint row at `end_time`, it is explicitly filtered
     according to the requested time grid, rather than blindly dropping the last row.
   - Provider responses are strictly verified: missing rows, duplicate timestamps, unexpected gaps,
     or invalid (`n.a.`) numerical values immediately raise `HorizonsParseError`.
   - Grid compatibility: Sun and Earth time series must have identical row counts and timestamps.
3. **Observation Points:**
   - Evaluated under identical airless topocentric geometric rules as Stage 1/2 single observation:
     - Geometric horizon: `horizon_elevation_deg = 0.0`.
     - Visibility threshold: `horizon_elevation_deg + visibility_margin_deg`.
     - Strict visibility comparison: `elevation_deg > threshold`.
     - Golden window: `is_golden_window = sun.visible and earth.visible`.
     - Local ENU unit vector normalization: $e^2 + n^2 + u^2 = 1.0 \pm 10^{-6}$.
4. **Continuous Window Detection:**
   - Each sample $t_i$ represents the interval $[t_i, \min(t_i + \text{step}, \text{end\_time}))$.
   - Consecutive `True` samples merge into a continuous interval.
   - `False` samples split the interval.
   - Edge cases handled: all false (returns `[]`), all true (spans entire period), isolated samples,
     first sample true, last sample true, and multiple independent windows.
5. **Physical Sunset / Earthset Events:**
   - A sunset or earthset is detected **only** on an observed `True -> False` transition between
     adjacent sample points ($t_i$ visible, $t_{i+1}$ invisible), occurring at $t_{i+1}$.
   - Closing a window at `end_time` is not an observed physical transition and does **not** record a set event.
   - If no transition occurs in the period, `null` is returned.
6. **Time-Step Resolution Limitation:**
   - Observations are sampled at discrete intervals defined by `step_minutes` (e.g. 15, 30, 60, 120, 180, 360m).
   - Shorter astronomical events between sample points (such as short occultations or brief dips below horizon lasting less than `step_minutes`) may not be captured.
   - Interval boundaries have step accuracy: each favorable point represents $[t_i, \min(t_i + \text{step}, \text{end\_time}))$.

## 4. Handoff Specifications for Sasha and Slavik

### Handoff for Sasha (Frontend UI & Charts)
- **Timeline Points Array:** Access `points` containing `sun`, `earth`, `is_golden_window`, and ISO `timestamp`. Each body contains `azimuth_deg`, `elevation_deg`, `horizon_elevation_deg` (0.0), and boolean `visible`.
- **Interval Bars:** Use `sunlight_windows`, `earth_visibility_windows`, and `golden_windows`. Each interval item provides `start_time`, `end_time`, and float `duration_hours`.
- **Summary Cards:** Display `summary.sunlit_hours`, `summary.sunlit_pct`, `summary.earth_visible_hours`, `summary.earth_visible_pct`, `summary.golden_hours`, `summary.golden_pct`, `summary.longest_golden_window_hours`, `summary.average_sun_elevation_deg`, `summary.next_sunset_at`, and `summary.next_earthset_at`.

### Handoff for Slavik (3D Local Scene & Map Trajectories)
- **Three.js ENU Coordinate Mapping:**
  - $x = \text{east}$
  - $y = \text{up}$
  - $z = -\text{north}$
- **Vectors Invariance:** For every point, $\text{east}^2 + \text{north}^2 + \text{up}^2 = 1.0 \pm 10^{-6}$.
- **Sun & Earth Directions:** Located on `point.sun.direction_enu` and `point.earth.direction_enu`.

### Example Payload Structure
```json
{
  "start_time": "2027-07-15T00:00:00Z",
  "end_time": "2027-07-16T00:00:00Z",
  "step_minutes": 360,
  "total_samples": 4,
  "points": [
    {
      "timestamp": "2027-07-15T00:00:00Z",
      "sun": {
        "azimuth_deg": 177.278712,
        "elevation_deg": 1.490814,
        "horizon_elevation_deg": 0.0,
        "visible": true,
        "direction_enu": { "east": 0.047464, "north": -0.998537, "up": 0.026017 }
      },
      "earth": {
        "azimuth_deg": 142.714718,
        "elevation_deg": 5.123456,
        "horizon_elevation_deg": 0.0,
        "visible": true,
        "direction_enu": { "east": 0.603348, "north": -0.792376, "up": 0.089282 }
      },
      "is_golden_window": true
    }
  ],
  "sunlight_windows": [
    { "start_time": "2027-07-15T00:00:00Z", "end_time": "2027-07-15T06:00:00Z", "duration_hours": 6.0 }
  ],
  "earth_visibility_windows": [
    { "start_time": "2027-07-15T00:00:00Z", "end_time": "2027-07-15T06:00:00Z", "duration_hours": 6.0 }
  ],
  "golden_windows": [
    { "start_time": "2027-07-15T00:00:00Z", "end_time": "2027-07-15T06:00:00Z", "duration_hours": 6.0 }
  ],
  "summary": {
    "sunlit_hours": 6.0,
    "sunlit_pct": 25.0,
    "earth_visible_hours": 6.0,
    "earth_visible_pct": 25.0,
    "golden_hours": 6.0,
    "golden_pct": 25.0,
    "longest_golden_window_hours": 6.0,
    "average_sun_elevation_deg": 1.490814,
    "next_sunset_at": null,
    "next_earthset_at": null
  }
}
```

## 5. Verification & Checks

| Check | Target | Expected | Result |
|---|---|---|---|
| `test_time_grid_respects_half_open_period_and_step_counts` | Time grid generator | 720 pts (30d@60m), 168 pts (14d@120m), no sample at end | PASSED |
| `test_time_grid_validates_inputs_strictly` | Time grid input validation | Rejects duration bounds, unsupported steps, naive timestamps | PASSED |
| `test_continuous_windows_handles_all_required_topologies` | Window interval merger | All false, all true, first true, last true, middle true, split | PASSED |
| `test_summary_metrics_reproduce_contract_example` | Summary calculations | Exact match with `contracts/examples/timeline-two-golden-windows.json` | PASSED |
| `test_sunset_and_earthset_require_physical_transition` | Sunset / Earthset transitions | True->False only; no false trigger on sunrise, all-true, or end-of-period | PASSED |
| `test_horizons_provider_filters_endpoint_row_correctly` | HorizonsProvider series query | Filters endpoint row at `end_time` explicitly without truncation | PASSED |
| `test_horizons_provider_rejects_duplicates_gaps_and_corrupt_data` | Provider parsing validation | Rejects duplicates, gaps, `n.a.` values, and provider errors | PASSED |
| `test_calculate_geometric_timeline_agrees_with_single_observation` | Physics consistency | Point 0 matches `calculate_geometric_observation` within $10^{-6}$ | PASSED |
| `test_live_horizons_timeline_query` | Live JPL Horizons API | Live bounded series query (Sun and Earth) returns verified samples | PASSED |

## 5. Reproduction

Execute full astronomy test suite:

```powershell
& C:\Users\manin\AppData\Roaming\Python\Python315\Scripts\uv.exe --directory backend run --locked pytest tests/test_timeline_service.py
```

Execute with live JPL Horizons query:

```powershell
$env:TEST_LIVE_HORIZONS="1"
& C:\Users\manin\AppData\Roaming\Python\Python315\Scripts\uv.exe --directory backend run --locked pytest tests/test_timeline_service.py -k test_live_horizons_timeline_query
```
