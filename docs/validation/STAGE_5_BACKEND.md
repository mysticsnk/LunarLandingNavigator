# Stage 5 Backend Comparison Integration

## Implemented

- Added strict comparison request validation for 2–6 scenarios, unique labels,
  catalog/custom sites, independent UTC start times, common calculation settings,
  supported dates, and the existing timeline duration and step limits.
- Added `POST /api/v1/ephemeris/compare`. Accepted requests use the existing
  durable job envelope with kind `comparison`. Every scenario is resolved in
  request order; terrain support is checked for every location before accepting
  a terrain comparison.
- Comparison cache identity preserves scenario order and labels, normalized
  locations, each start time and model/dataset version, and all shared settings.
- Added immutable result validation and per-scenario provenance. The common
  `meta.terrain_dataset_id` is populated only when all terrain scenarios share
  the same dataset; mixed datasets use null while each scenario reports its own
  model, dataset, and sources.
- Added a durable job-kind migration. Existing claims, lease fencing, recovery,
  atomic result publication, result retention, and cache storage are reused.
- Added a worker placeholder that records `COMPARISON_UNAVAILABLE` as a
  structured failed-job error. It does not invent successful results.

## Calculation service integration blocker

The agreed comparison/timeline ranking service is not present in this checkout
or in the locally available `origin/Denis` branch. The comparison route and job
infrastructure are ready, but the worker deliberately fails comparison jobs
until that service is integrated. Replace the explicit worker placeholder with
the service-owned sequential scenario evaluation and v1 ranking call before
calling Stage 5 complete. Do not enable successful comparison execution by
adding a second score or timeline implementation here.

The planned service must receive the frozen normalized scenario contexts, use
each scenario's pinned terrain dataset/model version, evaluate scenarios with
bounded provider concurrency, and return the agreed ranked result with actual
provenance. A failure in any scenario must fail the entire comparison job.

## Contract provenance extension

The owner approved the minimal extension before implementation. Each
`ranked_scenarios[]` item contains:

```json
{
  "provenance": {
    "model_version": "...",
    "terrain_dataset_id": "...",
    "sources": []
  }
}
```

For geometric scenarios, `terrain_dataset_id` is null. The shared comparison
metadata reports a dataset ID only when every terrain scenario shares that ID;
it is null for geometric comparisons and mixed terrain datasets. Generated
frontend API types match the updated OpenAPI schema.

## Verification

Commands run:

```powershell
cd backend
.\.venv\Scripts\ruff.exe check app\requests.py app\results.py app\storage.py app\routes.py app\worker.py migrations\versions\0004_stage5_comparison_jobs.py tests\test_contract.py tests\test_stage5_comparison.py
.\.venv\Scripts\ruff.exe format --check app\requests.py app\results.py app\storage.py app\routes.py app\worker.py migrations\versions\0004_stage5_comparison_jobs.py tests\test_contract.py tests\test_stage5_comparison.py
.\.venv\Scripts\pytest.exe tests\test_stage5_comparison.py -q
```

Recorded results: full Ruff check passed; 63 Python files were formatted;
21 comparison tests passed, including request limits, cache identity, accepted
job/result lifecycle with a controlled fixture, explicit worker failure, and
terrain rejection when any scenario lacks coverage. Four OpenAPI/example tests
passed, including validation of distinct per-scenario dataset provenance.
`frontend/npm run check:api` passed after regenerating the TypeScript schema.
The full backend suite passed 374 tests with 16 skipped after the final changes.

The PostgreSQL integration test is present in
`backend/tests/test_stage1_postgres.py`. It uses the existing `_test`-database
guard, but was not run because `TEST_DATABASE_URL` is not configured. No live
comparison was run; successful execution is blocked by the missing service.

## Reproduction and configuration

Upgrade an isolated PostgreSQL database whose name ends in `_test`:

```powershell
cd backend
$env:TEST_DATABASE_URL = "postgresql+psycopg://test_user:test_password@127.0.0.1:5432/lunar_navigator_stage5_test"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\pytest.exe tests\test_stage1_postgres.py::test_comparison_job_lifecycle_and_cache_with_postgresql -q -p no:cacheprovider
```

The comparison request uses the same fields as
`contracts/examples/comparison-request.json`. Poll the returned status URL and
then fetch the result URL. Until the calculation service is integrated, the
durable worker intentionally returns a failed job with
`COMPARISON_UNAVAILABLE`.

## Remaining checks and limitations

- Run the PostgreSQL integration test against a dedicated test database.
- Integrate the calculation service and run deterministic controlled-result
  acceptance cases through the actual executor.
- Run a bounded real multi-scenario comparison after the service is available.
- The API operation remains marked planned in OpenAPI until the comparison job
  can produce a real result.
