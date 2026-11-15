# Stage 3 frontend integration

## Implemented workflow

The workspace keeps the single-instant observation workflow and adds a
multi-day geometric timeline mode. Both modes use the same catalog/custom site,
explicit UTC start time, observer height, and visibility margin. Timeline
requests validate a 1–30 day duration, a supported sampling step, and the
supported UTC range before submission.

Timeline mode submits `POST /api/v1/ephemeris/timeline`, expects the existing
HTTP 202 job envelope with `kind: "timeline"`, polls the shared status URL at
two-second intervals without overlapping requests, and loads the result URL
after success. Replacing a request or leaving the workspace aborts client
polling. Late responses cannot replace a newer scenario. A provider or API
failure remains an error; the frontend does not substitute fixture data.

The result validator checks the complete half-open sample grid, point
timestamps, geometric point values, interval boundaries and durations, summary
metrics, and source metadata before display. The chart plots returned Sun/Earth
elevations at their returned UTC timestamps and marks the API's golden windows.
The UI lists sunlight, Earth visibility, and golden intervals separately,
labels period-boundary clipping, and presents API summary values without
recalculating them. Result provenance remains visible on demand, including
model version, `generated_at`, source names/versions, provider retrieval
timestamps, and URLs.

Playback selects returned samples locally. Previous/next, chart selection, the
sample slider, and play/pause update the numerical values and the existing local
scene from the same returned point. Playback stops at the final sample; it does
not interpolate values or submit additional requests. Sample resolution is
shown with timestamps. A null sunset/Earthset is described as no transition
observed in the computed period; a clipped interval does not create a set event.

## Verification

From `frontend/`, run:

```powershell
npm.cmd run check:api
npm.cmd run typecheck
npm.cmd run lint
npm.cmd test
npm.cmd run build
```

Recorded on 2026-11-14 with Node `v24.16.0` (the repository `.nvmrc` declares
`22.13.0`): generated API check, TypeScript, and lint passed; all 141 tests in
12 files passed; production build passed. Tests include the catalog submission,
contract request fields, status/result path, separate golden windows, clipped
boundary display, and scene synchronization for the selected returned sample.
The UI uses the controlled `timeline-two-golden-windows.json` contract example
in tests; those values are synthetic development fixtures, not live science.

The build reports a JavaScript chunk of about 1.23 MB minified, above Vite's
500 kB advisory threshold. No code splitting was introduced as part of this
workflow change.

## Configuration and limitations

Set the frontend API base URL in `frontend/.env.local` as `VITE_API_URL` when
the backend is not at `http://localhost:8000`. Start the API, PostgreSQL, and
the separate observation worker using the backend setup documented in
[`STAGE_3_BACKEND.md`](STAGE_3_BACKEND.md). Live provider verification requires
the configured backend/provider and a separate bounded smoke run; it was not
performed as part of this frontend implementation.

Timeline values describe the requested sample resolution. Sub-step physical
transitions, terrain occlusion, continuous event timing beyond the returned
intervals, and multi-site ranking are outside this stage.
