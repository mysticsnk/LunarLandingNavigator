# Stage 2 Frontend Workflow Integration Report

**Author / Role:** Frontend Workflow Integration Engineer (Stage 2)  
**Date:** 2026-11-14  
**Status:** VALIDATED  
**Scope:** Single-time observation user journey, state lifecycle, job submission & polling, numerical results & provenance, map & 3D scene integration, and independent failure isolation.

---

## 1. Authoritative Scenario State & Lifecycle

The frontend cleanly distinguishes between three distinct stages of scenario data:
1. **Currently edited form state (`draft`):** Held in local component state. Supports mutually exclusive catalog selection (`site_id`) vs custom coordinates (`latitude`, `longitude`, optional `name`).
2. **Submitted request snapshot (`buildRequest(draft)`):** Created upon form submission. Validates exact constraints (latitude $[-90, 90]^\circ$, longitude $[-180, 360)^\circ$, UTC time $[2000, 2050)$ with whole seconds, height $[0, 20]\text{ m}$, margin $[0, 5]^\circ$) and freezes the request payload sent to `POST /api/v1/ephemeris/now`.
3. **Observation result state (`result`):** Owned by `useObservation`. Any edit to the scenario immediately clears the active result (`observation.reset()`), guaranteeing an observation is never misattributed to modified form inputs. Before result readiness, the UI renders an explicit unknown state (`Sun visibility: Unknown · Earth visibility: Unknown · Simultaneous availability: Unknown`).

---

## 2. API Workflow, Polling & Race-Condition Guards

- **Catalog Loading & Navigation:** Loads `GET /api/v1/sites` with category filtering (`artemis`, `apollo`, `clps`, `international`) and 50-item pagination.
- **Job Submission:** `POST /api/v1/ephemeris/now` returns HTTP 202 Accepted with canonical `JobAccepted` response containing `job_id`, `status: "queued"`, `status_url`, and `result_url`.
- **Sequential Non-Overlapping Polling:** A timer invokes `GET {status_url}` every two seconds. Consecutive polls cannot overlap; at most one status request is in flight.
- **Terminal States & Error Preservation:**
  - On `job.status === 'succeeded'`: Automatically fetches `GET {result_url}` once and transitions to `phase: 'succeeded'`.
  - On `job.status === 'failed'`: Captures structured API error (`job.error`, including `request_id`) and displays error banner without falling back to synthetic defaults.
  - On `JOB_EXPIRED`, `JOB_NOT_FOUND`, `TERRAIN_UNAVAILABLE`, or `NETWORK_ERROR`: Aborts polling immediately and surfaces structured error details.
- **Stale Response Protection:** Every new submission or reset increments an internal `sequence` counter and aborts pending `AbortController` signals. Stale responses from request A arriving after request B are strictly discarded.
- **Cancellation Clarification:** Clicking "Stop waiting" clears local polling and timers with an explicit note: *"Stopping here leaves the server job running."* It does not claim server cancellation.

---

## 3. Numerical & Scientific Display

Results strictly reflect the API payload without frontend recomputation:
- **Location:** Normalized coordinates ($[-90, 90]^\circ$ lat, $[-180, 180)^\circ$ lon) and resolved site label.
- **Instant:** ISO 8601 UTC timestamp ending in `Z`.
- **Observations:** Azimuth $[0, 360)^\circ$, elevation $[-90, 90]^\circ$, geometric horizon ($0.0^\circ$), and strict inequality visibility boolean for both Sun and Earth.
- **Simultaneous Availability:** Reflects returned `is_golden_window` (`Yes` / `No`).
- **Metadata & Provenance:** Model version (`geometric-now-v1`), generation timestamp, `fresh` / `cached` badge, and complete scientific sources with links, ephemeris version (`DE441`), and retrieval timestamps.

---

## 4. Map & 3D Scene Integration

Slavik's exported `LunarMap` and `LunarScene` components receive the authoritative observation snapshot:
- **LunarMap:**
  - Displays registered Moon Trek WMTS and LROC WMS layers from `GET /api/v1/map/layers`.
  - Renders the selected coordinate marker derived directly from `result.site` (or the validated draft coordinates before submission).
  - Clicking inside the map surface selects coordinates and switches the scenario to custom mode without coordinate distortion.
- **LunarScene:**
  - Wrapped in `SceneErrorBoundary` to isolate WebGL context or Three.js failures.
  - Receives `observationPoint`, `site`, `dataStatus`, `observerHeightM`, and `sunDirectionEnu` / `earthDirectionEnu`.
  - Three.js local coordinate mapping: $x = \text{east}, y = \text{up}, z = -\text{north}$.
  - Derives HUD angles and visibility strictly from `observationPoint`.

---

## 5. Independent Failure Isolation

- **CSA Failure:** If `GET /api/v1/resources/csa` fails, the error is isolated to the CSA card. The observation setup form, map, scene, and numerical results remain fully functional.
- **Provider Text Safety:** All CSA article titles, summaries, and topics are rendered as plain React text nodes (no `dangerouslySetInnerHTML`).
- **Map / WebGL Failure:** A map tile load error or WebGL crash renders a local fallback with a retry action, keeping the remainder of the workspace operational.
- **No Synthetic Fallbacks:** Failed production requests never trigger automatic fallback to demo fixtures.

---

## 6. Checks Executed & Results

| Check | Tool / Scope | Result |
| --- | --- | --- |
| `npm run lint` | Oxlint (43 files, 116 rules) | **Passed** (0 warnings, 0 errors) |
| `npm run typecheck` | TypeScript (`tsc -b`) | **Passed** |
| `npm run check:api` | openapi-typescript contract validation | **Passed** (generated types match `openapi.v1.yaml`) |
| `npm test -- --run` | Vitest (10 test suites, 123 tests) | **123 passed** in 10.48s |
| `npm run build` | Vite production bundle build | **Passed** (`dist/` generated cleanly) |

---

## 7. Known Limitations

- Geometric horizon only ($0.0^\circ$). Requests for terrain mode return structured `TERRAIN_UNAVAILABLE`.
- Whole seconds are enforced for UTC inputs in Stage 2 to match backend ephemeris constraints.
