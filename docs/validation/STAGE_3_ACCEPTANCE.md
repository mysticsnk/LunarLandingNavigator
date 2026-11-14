# Stage 3 timeline acceptance report

**Date:** 2026-11-14
**Scope:** Timeline interval and metric acceptance, controlled service fixtures,
OpenAPI response fixture validation, and current frontend readiness. Production
timeline service, API, worker, and frontend files were not changed.

## Acceptance summary

| Area | Result | Evidence |
| --- | --- | --- |
| Required 12-hour interval topology | Passed | The controlled sequence `T T F T T F` produces `[00:00,04:00)` and `[06:00,10:00)`, 8 golden hours, longest 4 hours. |
| Topology and boundary cases | Passed | All-false, all-true, first-only, last-only, alternating, start-boundary, end clipping, missing-sample gap, ordering, and all allowed sample steps are checked. |
| Metric consistency and simultaneous visibility | Passed | Durations, non-overlap, period totals, percentages, longest segment, and `sun AND earth` are asserted. |
| OpenAPI result fixture | Passed | Existing controlled `timeline-two-golden-windows.json` validates against `TimelineResult`. |
| Controlled Horizons service behavior | Passed | Existing timeline service tests use `httpx.MockTransport`, including sample-to-single-observation consistency. |
| Live timeline sample comparison | Passed | One live timeline sample at `2027-07-15T00:00:00Z` matched a live single-observation call for Sun/Earth angles within `1e-6` degrees and for visibility/golden flags. |
| Timeline job/result integration | **Blocked** | Runtime POST returns 404; OpenAPI marks the timeline operation `planned` and says it is not registered. |
| Timeline chart and scene navigation | **Blocked** | The UI still renders the planned analytics placeholder; no timeline chart or sample playback path exists. |

## Controlled cases

The fixture at [`backend/tests/fixtures/timeline_acceptance.json`](../../backend/tests/fixtures/timeline_acceptance.json)
marks every state as synthetic controlled test data. The primary case uses the
12-hour half-open period `[2027-07-01T00:00:00Z, 2027-07-01T12:00:00Z)` and
two-hour samples at hours `0, 2, 4, 6, 8, 10`. It expects golden states
`true, true, false, true, true, false`; golden intervals `[0,4)` and `[6,10)`;
`golden_hours = 8`; and `longest_golden_window_hours = 4`.

The separate visibility sequence uses Sun `T T F F T T`, Earth `T F T T T F`,
and golden `T F F F T F`. Other explicit state cases cover no windows, one
period-long window, a window at either edge, and alternating separated windows.
Full expected intervals are listed in
[`STAGE_3_TEST_CASES.md`](STAGE_3_TEST_CASES.md).

Boundary checks confirm that points exclude `end_time`, a true final sample is
clipped at `end_time`, and clipping alone leaves sunset and Earthset null. A
missing sample leaves a gap between intervals. All allowed steps
`15, 30, 60, 120, 180, 360` minutes produce chronological half-open grids.

The contract requires integer `duration_days >= 1`, so the exact 12-hour case
cannot be submitted to the HTTP endpoint. It is tested at the interval helper
boundary; full-day request acceptance remains necessary after route integration.

## Failed integration acceptance and minimal reproduction

The contract contains `POST /api/v1/ephemeris/timeline` with
`x-implementation-status: planned`. A valid one-day geometric request was sent
through FastAPI `TestClient` with the normal database health dependency
overridden:

```json
{
  "site": {"latitude": -89.44, "longitude": 222.1},
  "start_time": "2027-07-15T00:00:00Z",
  "duration_days": 1,
  "step_minutes": 360,
  "horizon_mode": "geometric"
}
```

Observed response: `404 HTTP_404` (`Not Found`). The route is also absent from
the runtime `/openapi.json`. Consequently no timeline `202 Accepted` job can be
created, polled to success, or retrieved and validated as a persisted
`TimelineResult`. The generic Stage 2 job endpoints do not substitute for a
timeline submission path.

The UI review found `AnalyticsSlot` still labels timeline analytics “Planned for
a later stage”. There is no chart for separate intervals, no timeline timestamp
navigation, and no scene playback driven by returned timeline samples. The
single-observation scene tests remain applicable to that single-time path only.
The existing `App.test.tsx` also passed its guard against fabricated percentage,
watts, or Mbps displays; no solar-generation power display was found.

## Live verification

With `TEST_LIVE_HORIZONS=1`, the bounded acceptance test queried the real JPL
Horizons provider for a one-day timeline at six-hour steps, then for the
corresponding single observation at the first timestamp. Provider timeout was
12 seconds and retries were disabled. The selected sample matched in timestamp,
Sun/Earth visible flags, golden flag, and Sun/Earth azimuth/elevation (absolute
tolerance `1e-6` degrees). This validates the service/provider seam only; it
does not exercise a persisted job or frontend workflow. No state was inferred
from the Shackleton site name or latitude.

## Checks and actual results

| Command/check | Result |
| --- | --- |
| `ruff check tests/test_timeline_acceptance.py` | Passed. |
| `pytest tests/test_timeline_acceptance.py tests/test_timeline_service.py -p no:cacheprovider` | 20 passed, 2 live checks skipped by default, 1 Starlette/AnyIO deprecation warning. |
| `TEST_LIVE_HORIZONS=1 pytest tests/test_timeline_acceptance.py -k test_live_timeline_sample_matches_single_observation -p no:cacheprovider` | 1 passed, 11 deselected; live Horizons comparison completed in 3.08s; same deprecation warning. |
| `npm.cmd run test -- src/App.test.tsx` | 13 passed. |
| `npm.cmd run test -- src/features/scene/Scene.test.tsx` | 16 passed; Three.js CommonJS deprecation warning. |
| OpenAPI `TimelineResult` fixture validation | Passed for the existing controlled contract example. |
| FastAPI timeline submission reproduction | Failed acceptance as expected: 404; runtime route absent. |

The following command reproduces the primary checks in PowerShell:

```powershell
Push-Location backend
.venv/Scripts/ruff.exe check tests/test_timeline_acceptance.py
.venv/Scripts/python.exe -m pytest tests/test_timeline_acceptance.py tests/test_timeline_service.py -p no:cacheprovider
$env:TEST_LIVE_HORIZONS = "1"
.venv/Scripts/python.exe -m pytest tests/test_timeline_acceptance.py -k test_live_timeline_sample_matches_single_observation -p no:cacheprovider
Remove-Item Env:TEST_LIVE_HORIZONS
Pop-Location

Push-Location frontend
npm.cmd run test -- src/App.test.tsx
npm.cmd run test -- src/features/scene/Scene.test.tsx
Pop-Location
```

## Remaining acceptance work and coordination

- Yaroslav must register the timeline submission with the durable job worker,
  persist the full contract response and metadata, and demonstrate submit/status/
  result behavior with a controlled provider fixture.
- Denys should review the isolated acceptance test location
  `backend/tests/test_timeline_acceptance.py` and fixture location
  `backend/tests/fixtures/timeline_acceptance.json` before merging them into the
  team's maintained test layout.
- Sasha must connect actual returned intervals, timestamps, and resolution to a
  timeline chart/navigation UI; Slavik must connect the selected returned sample
  to scene playback. Keep the interval lists separate and avoid recomputing
  astronomical values in React.
- Repeat integrated UI checks for separate windows, real timestamps, selected
  scene sample, period-end clipping label, visible time resolution, and absence
  of watts or an invented solar-generation percentage.
- Run a bounded real-provider job through the completed API/worker path and
  compare multiple selected persisted samples against single-observation results.

No active Denys, Yaroslav, Sasha, or Slavik collaboration session was available
during this validation. Changes were isolated to the independent acceptance
test, its controlled fixture, and these validation documents; no other owner's
production files were edited.
