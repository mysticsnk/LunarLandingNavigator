# Stage 3 backend integration validation

## Scope and implementation

The integrated API now supports `POST /api/v1/ephemeris/timeline` for a single
geometric timeline. It accepts catalog or custom coordinates, validates the
requested UTC period and sampling step, returns the existing HTTP 202 job
acceptance envelope with `kind: "timeline"`, and uses the durable PostgreSQL
worker and existing job status/result routes. Terrain requests return
`422 TERRAIN_UNAVAILABLE`; comparison and terrain occlusion remain out of scope.

The worker calls Denys's `calculate_geometric_timeline` service and the real
Horizons provider. It validates the complete result before atomically storing
the succeeded job and cache entry. Provider errors fail the job through the
existing structured error path. Cache identity contains normalized coordinates,
start time, duration, step, height, visibility margin, horizon mode, job kind,
and timeline model version. The existing `now` cache identity remains unchanged.

The shared jobs table now permits `now` and `timeline`; migration
`0002_stage3_timeline_jobs` updates the PostgreSQL check constraint without
rebuilding the table. Existing queued `now` jobs remain executable. The result
model validates the half-open sample grid, sample count, metadata resolution,
window boundaries/durations, and event timestamps. Sunset and Earthset are
reported only for sampled visible-to-invisible transitions; a window ending at
the period boundary does not create an event.

The astronomy service's mean elevation is an arithmetic mean over equally
spaced samples. Because every sample represents the same duration, this equals
the contract's duration-weighted mean. No service calculation change was needed.

## Integration findings

- The timeline route was present in the contract but not registered in runtime.
- Durable jobs restricted `kind` to `now`, result reads validated only
  `NowResult`, and worker execution always called the single-time service.
- The timeline integration now connects request validation, site resolution,
  durable submission, the provider-backed timeline service, result validation,
  atomic publication, cache reuse, and job status/result reads.
- The Stage 3 PostgreSQL test exercises a catalog site and normalized custom
  coordinates, controlled Horizons responses parsed by the production provider,
  168 returned samples for 14 days at 120-minute steps, cached reuse, a distinct
  sampling step, and an unavailable provider.
- A result whose Earth visibility remains true through the period end has an
  interval ending at `end_time` and a null `next_earthset_at`.
- Generated frontend API types were regenerated from the agreed OpenAPI
  contract. No frontend calculation logic was added.

## Configuration and reproduction

Use Python 3.12 with `backend/uv.lock` and Node 22 as declared by the project.
Install Python dependencies from `backend/` with `python -m uv sync --locked
--python 3.12`. Generate/check API types from `frontend/` with `npm run
generate:api` and `npm run check:api`.

PostgreSQL integration tests write to `TEST_DATABASE_URL`. Use a disposable
database named `test` or ending in `_test`; the test fixture applies Alembic
migrations and writes jobs and cache entries. On PowerShell, for example:

```powershell
docker run --rm --name lunar-stage3-test `
  -e POSTGRES_USER=lunar_test `
  -e POSTGRES_PASSWORD=<local-test-password> `
  -e POSTGRES_DB=lunar_test `
  -p 127.0.0.1:55435:5432 postgres:16.6-alpine
```

In another terminal from `backend/`:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://lunar_test:<local-test-password>@127.0.0.1:55435/lunar_test"
python -m uv run --locked pytest -m integration -q
```

The bounded live Stage 3 check runs the full integrated job path and makes two
real Horizons series requests for 14 days at a 120-minute step (168 samples):

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://lunar_test:<local-test-password>@127.0.0.1:55435/lunar_test"
$env:TEST_LIVE_HORIZONS = "1"
python -m uv run --locked pytest tests/test_stage1_postgres.py::test_live_timeline_job_persists_real_horizons_result -q -s
```

The live test has no performance threshold. It reports measured worker
execution time and serialized result size for that run only. It must not be
replaced by the controlled-provider integration test as evidence of live data.

## Verification performed

Commands run in this workspace:

- `python -m ruff check app tests migrations` — passed.
- `python -m ruff format --check app tests migrations` — passed.
- `pytest -m "not integration" -q` — 301 passed, 5 explicitly gated live checks
  skipped because `TEST_LIVE_HORIZONS` was unset, 8 integration tests deselected.
- `pytest -m integration -q` on a newly created disposable PostgreSQL 16.6
  database — 6 passed, 2 live checks skipped because `TEST_LIVE_HORIZONS` was
  unset. Alembic upgraded the database through head, including the Stage 3 job
  kind constraint.
- The separate live integrated timeline check passed against NASA/JPL Horizons:
  168 samples, 3.018 seconds measured worker execution, 79,761 serialized JSON
  bytes. This is one run, not a universal performance guarantee.
- `npm run generate:api` and `npm run check:api` — passed.
- `npm run typecheck` — passed; `npm test -- --run` — 125 passed across 10 files.
- `npm run build` — passed. Vite emitted its existing large-chunk warning
  (1,203.13 kB uncompressed JavaScript bundle).

The backend checks emitted one existing Starlette/AnyIO deprecation warning;
the frontend test run emitted the existing Three.js CommonJS deprecation warning.
PostgreSQL integration coverage includes both catalog and fresh
custom-coordinate timelines.

## Remaining limits

- Terrain mode remains explicitly unavailable; no DEM occlusion is performed.
- Live provider values can vary by request time and provider data version. The
  deterministic tests use controlled fixtures and do not claim scientific live
  verification.
- The measured live duration and payload size apply only to the run above.
- Timeline points and intervals use the selected sampling resolution; event
  transitions are sampled transitions, not continuous root-finding results.
