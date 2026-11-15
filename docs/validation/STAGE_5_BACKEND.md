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
- Integrated the comparison service with sequential timeline evaluation,
  existing per-timeline caching, exact scenario provenance, and atomic job
  result publication. Any failed scenario fails the comparison job.

## Calculation service

The service in `app.astronomy.comparison` owns the v1 scoring formula and
ordering. The worker evaluates scenarios one at a time using the existing
timeline implementation and provider lock, then passes validated timeline
summaries and provenance to that service. A failure in any scenario fails the
whole job; partial rankings are not published.

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
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\pytest.exe -q
```

Current results from this checkout:

- `ruff check .`: passed.
- `ruff format --check .`: passed; 67 files already formatted.
- Full backend suite: 403 passed, 16 skipped, 1 Starlette/AnyIO deprecation
  warning.
- Focused comparison, acceptance, ranking, and contract tests: 79 passed,
  1 warning.
- Frontend API type check and lint: passed; frontend tests: 177 passed;
  production build: passed with Vite's existing large-chunk warning.
- The comparison-result fixture now carries its synthetic timeline model in
  scenario provenance; the comparison-level model remains the ranking model.

The PostgreSQL integration test is present in
`backend/tests/test_stage1_postgres.py`. It uses the existing `_test`-database
guard, but was not run because `TEST_DATABASE_URL` is not configured. Live
Horizons and paired terrain comparisons were not run. These are separate from
the controlled deterministic tests.

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
then fetch the result URL. The worker runs scenarios sequentially through the
existing timeline service and provider concurrency lock; it fails the complete
comparison job if any scenario fails.

## Remaining checks and limitations

- Run the PostgreSQL integration test against a dedicated test database.
- Run a bounded real multi-scenario comparison.
- Visual-check the comparison UI against a running backend.
