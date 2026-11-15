# Stage 3 timeline acceptance report

**Date:** 2026-11-14
**Scope:** Timeline interval and metric acceptance, integrated timeline API and
worker, controlled service fixtures, and frontend timeline interaction.

## Acceptance summary

| Area | Result | Evidence |
| --- | --- | --- |
| Required 12-hour interval topology | Passed | The controlled sequence `T T F T T F` produces `[00:00,04:00)` and `[06:00,10:00)`, 8 golden hours, longest 4 hours. |
| Topology and boundary cases | Passed | All-false, all-true, first-only, last-only, alternating, start-boundary, end clipping, missing-sample gap, ordering, and all allowed sample steps are checked. |
| Metric consistency and simultaneous visibility | Passed | Durations, non-overlap, period totals, percentages, longest segment, and `sun AND earth` are asserted. |
| OpenAPI result fixture | Passed | Existing controlled `timeline-two-golden-windows.json` validates against `TimelineResult`. |
| Controlled Horizons service behavior | Passed | Existing timeline service tests use `httpx.MockTransport`, including sample-to-single-observation consistency. |
| Live timeline sample comparison | Passed | One live timeline sample at `2027-07-15T00:00:00Z` matched a live single-observation call for Sun/Earth angles within `1e-6` degrees and for visibility/golden flags. |
| Timeline job/result integration | Passed in Stage 3 backend handoff | The registered route returns 202 and uses durable job/result endpoints; see [`STAGE_3_BACKEND.md`](STAGE_3_BACKEND.md) for PostgreSQL and provider evidence. |
| Timeline chart and scene navigation | Passed in frontend regression suite | Chart uses returned elevations and golden intervals; selecting or playing a sample updates the scene from that returned point. |

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

The earlier acceptance run was performed before timeline route integration. At
that time, the route was absent and a valid request returned 404. The current
repository has since integrated this path; use the backend handoff for current
route, worker, PostgreSQL, and provider evidence. The old reproduction below is
historical and is not a statement of current behavior:

```json
{
  "site": {"latitude": -89.44, "longitude": 222.1},
  "start_time": "2027-07-15T00:00:00Z",
  "duration_days": 1,
  "step_minutes": 360,
  "horizon_mode": "geometric"
}
```

The UI previously rendered a placeholder. It now submits a timeline job,
polls through the shared job routes, validates the complete returned grid,
shows the API's intervals and summary, and drives local sample selection and
playback without additional requests. Regression coverage uses the explicitly
synthetic contract fixture; it is not live scientific verification.

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
| Frontend timeline regression | Current full run: 141 tests passed across 12 files, including timeline job lifecycle, contract payload, intervals, clipping label, and selected scene sample. |
| `npm.cmd run test -- src/features/scene/Scene.test.tsx` | 16 passed; Three.js CommonJS deprecation warning. |
| OpenAPI `TimelineResult` fixture validation | Passed for the existing controlled contract example. |
| Earlier FastAPI timeline submission reproduction | Historical result before integration: 404; runtime route was absent at that time. |
| `npm run check:api` | Passed. |
| `npm run typecheck` | Passed. |
| `npm run lint` | Passed with no lint findings. |
| `npm test` | 141 passed across 12 files; Three.js CommonJS deprecation warning. |
| `npm run build` | Passed; Vite reports the large JavaScript chunk warning (1,229.40 kB minified). |

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
npm.cmd run check:api
npm.cmd run typecheck
npm.cmd run lint
npm.cmd test
npm.cmd run build
Pop-Location
```

The recorded frontend run used Node `v24.16.0`; the repository's `.nvmrc`
specifies `22.13.0`.

## Remaining acceptance work and limitations

- Automated frontend tests do not replace a visual browser review against a
  configured live backend.
- The earlier live service comparison does not verify a live persisted job in
  this run. Repeat a bounded provider-backed timeline job when the provider and
  isolated PostgreSQL test database are available.
- The UI shows sampled values at the requested resolution. It does not infer
  sub-step transitions, continuous windows, physical terrain occlusion, or
  multi-site ranking.

This document retains the initial route-absence reproduction as history; it is
not a current blocker. See [`STAGE_3_BACKEND.md`](STAGE_3_BACKEND.md) for the
integrated backend implementation and its recorded evidence.
