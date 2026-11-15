# Stage 2 backend integration validation

## Scope

Stage 2 verifies the single-time geometric observation path from API submission
through durable PostgreSQL jobs, the existing Horizons observation service,
stored results, and status/result reads. Timeline, comparison, and physical
terrain occlusion remain out of scope.

## Integration findings

- The default FastAPI application registers the real map router alongside the
  API routes. The runtime boundary in `docs/API_V1.md` had fallen behind the
  completed integration and now lists the registered map routes.
- Production worker execution uses the existing `calculate_geometric_observation`
  service with the real JPL Horizons provider. Executor injection is an explicit
  Python argument used by tests; no environment switch selects fixture results.
- Job completion and result persistence happen in one database transaction.
  Lease token and expiry predicates fence recovered workers; cache publication
  shares the same transaction.
- PostgreSQL integration coverage now exercises the HTTP API with the versioned
  catalog, a catalog-site request, controlled Horizons HTTP responses parsed by
  the production provider, result persistence, a custom-coordinate cache hit,
  a distinct-margin cache miss, provider failure, and independent map/CSA errors.
- The PostgreSQL integration fixture rejects `TEST_DATABASE_URL` values whose
  database is not named `test` or `*_test` before applying migrations.

## Configuration and reproduction

Use Python 3.12 and the committed `backend/uv.lock`. Install dependencies from
the backend directory with `python -m uv sync --locked --python 3.12`. The API
and worker must use the same `DATABASE_URL` and run as separate processes. The
root `.env` contains local database settings; do not replace an existing file.

PostgreSQL integration tests write to `TEST_DATABASE_URL`. Use a dedicated,
disposable database named `test` or ending in `_test`; the tests apply Alembic
migrations and write catalog/job/cache rows. The CI workflow provisions an
isolated PostgreSQL service named `lunar_test` for each run.

For local PowerShell verification, start a temporary PostgreSQL container with
no mounted volume in one terminal:

```powershell
docker run --rm --name lunar-stage2-test -e POSTGRES_USER=lunar_test -e POSTGRES_PASSWORD=stage2_only -e POSTGRES_DB=lunar_test -p 127.0.0.1:55434:5432 postgres:16.6-alpine
```

Stop it with Ctrl+C after verification. The password is only for this disposable
local container.

From `backend/`:

```powershell
python -m uv run --locked ruff check .
python -m uv run --locked ruff format --check .
python -m uv run --locked pytest -m "not integration" -q
$env:TEST_DATABASE_URL = 'postgresql+psycopg://<test-user>:<test-password>@127.0.0.1:5432/lunar_test'
python -m uv run --locked pytest -m integration -q
```

The live Horizons control is separate and opt-in. It makes four bounded requests
to the official provider for the documented Shackleton and Faustini controls:

```powershell
$env:TEST_LIVE_HORIZONS = '1'
python -m uv run --locked pytest tests/probes/test_stage2_live_observation.py -q
```

This probe checks real provider output against the existing recorded control
values. Deterministic CI uses controlled Horizons responses and does not contact
external providers.

The full live API/worker workflow also ran against the disposable PostgreSQL
container with `TEST_LIVE_HORIZONS=1` and the production spawned worker. It
returned a fresh stored result with both JPL source records and matched the
Shackleton controls. The live verification commands were:

```powershell
$env:TEST_LIVE_HORIZONS = '1'
python -m uv run --locked pytest -m integration -q
python -m uv run --locked pytest tests/probes/test_stage2_live_observation.py -q
```

## Job and recovery behavior

Accepted requests return HTTP 202 and persist the raw submission plus resolved
scientific inputs before a worker handles them. The worker claims jobs using
`FOR UPDATE SKIP LOCKED`, a PostgreSQL advisory provider slot, and a lease token.
Expired running leases return to the queue on the next worker poll. A stale
attempt cannot publish after recovery because result publication checks the
current lease token and expiry. Result/status updates and successful cache
publication commit atomically. Results remain available for at least seven days.

Provider errors become failed jobs with the agreed error object. Result reads
return the contract's `JOB_FAILED`, `JOB_NOT_READY`, `JOB_NOT_FOUND`, or
`JOB_EXPIRED` envelopes. CSA and map failures use their own routes and do not
mutate observation jobs.

## Checks and actual results

| Command | Result |
| --- | --- |
| `ruff check .` | Passed. |
| `ruff format --check .` | Passed; 41 files already formatted. |
| `pytest -m "not integration" -q` | Historical recorded run: 273 passed, 3 opt-in live/integration cases skipped, 6 integration tests deselected. |
| `TEST_LIVE_HORIZONS=1 pytest -m integration -q` against disposable PostgreSQL | 6 passed, including the full live API/worker/Horizons workflow and PostgreSQL recovery/cache tests. |
| `TEST_LIVE_HORIZONS=1 pytest tests/probes/test_stage2_live_observation.py -q` | 2 passed; both documented control sites matched. |

Pytest emitted one upstream AnyIO `BlockingPortal` deprecation warning in each
run. No assertion or application warning failed a check. Database-writing tests
used a fresh PostgreSQL 16.6 Alpine container with no mounted volume; it was
stopped and removed after the run. The full live test used actual Horizons
responses; controlled fixture responses were used only in deterministic tests.
Historical Stage 1 counts in `docs/integration/STAGE1_COMPLETION.md` are not
evidence for these Stage 2 checks.

The current checkout's collection differs from the historical reports:
`pytest --collect-only -q -m "not integration"` collected 289 of 295 tests and
deselected 6 integration tests. A current execution attempt did not complete:
the TestClient portal timed out while creating a Windows socket pair in this
restricted environment. The astronomy handoff records a different historical
count (277 passed, 2 skipped, 4 deselected); neither report is a verified result
for this checkout.

## Remaining limits

- The deterministic PostgreSQL integration scenario uses controlled provider
  responses. The full live API/worker workflow was separately verified above.
- Production observations remain geometric and whole-second. Terrain mode fails
  explicitly with `TERRAIN_UNAVAILABLE`.
- The frontend UI is outside this backend handoff; end-to-end browser evidence
  must be recorded separately.
- Terrain occlusion remains outside Stage 2. Terrain requests fail explicitly
  with `TERRAIN_UNAVAILABLE` until a later stage implements physical horizons.
