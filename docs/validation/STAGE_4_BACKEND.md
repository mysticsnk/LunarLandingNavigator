# Stage 4 Backend Terrain Integration

## Implemented

- Added an immutable PostgreSQL registry for prepared terrain datasets and
  their display regions. The migration registers terrain region identifiers
  for the Shackleton Connecting Ridge and Faustini Rim A catalog entries.
- Added `GET /api/v1/terrain/coverage` and
  `GET /api/v1/terrain/regions/{region_id}/heightmap`. Coverage uses the
  numerical raster sampler and the terrain service's observer support check;
  heightmaps are bounded local ENU grids whose rows increase north and whose
  columns increase east.
- Added a windowed Rasterio reader. It does not load the source raster into
  memory, checks the lunar south-polar stereographic projection and 1,737,400 m
  sphere, bilinearly samples numerical elevations, and rejects no-data rather
  than filling it.
- Connected terrain now and timeline jobs to the existing astronomy terrain
  service. Accepted jobs retain the selected immutable dataset and processing
  version. Missing coverage and unreadable assets fail explicitly; there is no
  geometric fallback. The terrain dataset ID and processing version participate
  in cache identity.
- Registering the same raster is idempotent. A new raster checksum creates a
  new immutable dataset row and advances the named display-region pointers;
  previously accepted jobs continue to resolve their pinned dataset ID.
- Added an explicit, resumable Product 90 downloader and a readiness command.
  Downloads are placed under `%LOCALAPPDATA%/LunarLandingNavigator/terrain`
  (or the equivalent local application data directory), outside Git. Large
  downloads require an explicit flag. Registration re-verifies the prepared
  raster and its manifest before writing the dataset registry.

## Dataset

The only registered-source implementation in this integration is NASA/GSFC LOLA
PGDA Product 90, `LDEM_80S_20MPP_ADJ.TIF`: 30,400 × 30,400 Float32 samples at
20 m, south-polar stereographic X/Y in metres, MOON_ME / JPL DE421, referenced
to a 1,737,400 m sphere. Product 78 local rasters remain excluded from physical
calculations because their product-specific vertical reference and full horizon
coverage are not verified. Product metadata: [PGDA Product 90](https://pgda.gsfc.nasa.gov/products/90).

The Product 90 transfer completed at 2,696,082,051 bytes. Full-file SHA-256 is
`09b7ca80f9e6a146f970225d18af72fc02787669b3ef51b888e347d2b6845649`. Raster
metadata and observer samples at the Shackleton and Faustini reference points
passed readiness checks; the external manifest reports `terrain_ready`, frame
`MOON_ME / JPL DE421`, target radius 1,737,400 m, and processing version
`lunar-south-polar-v1`. The raster and manifest are stored under
`%LOCALAPPDATA%/LunarLandingNavigator/terrain`, outside the repository.

The local development PostgreSQL database was upgraded to
`0003_stage4_terrain_registry`, and dataset
`lola-product-90-09b7ca80f9e6a146` was registered. The registry stores the asset
path outside Git and pins the checksum and processing version. The full terrain
now/timeline job path and live Horizons calls have not been run, so successful
observer samples do not prove that every requested horizon ray has complete
coverage.

## Setup and reproduction

From `backend`, after PostgreSQL is available and `.env` points to the intended
database:

```powershell
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe tools\prepare_terrain.py LDEM_80S_20MPP_ADJ.TIF --download --allow-large-download --resume
..\.venv\Scripts\python.exe tools\prepare_terrain.py LDEM_80S_20MPP_ADJ.TIF --file "$env:LOCALAPPDATA\LunarLandingNavigator\terrain\LDEM_80S_20MPP_ADJ.TIF"
..\.venv\Scripts\python.exe tools\register_terrain.py "$env:LOCALAPPDATA\LunarLandingNavigator\terrain\LDEM_80S_20MPP_ADJ.TIF.terrain.json"
```

The migration and registration commands write to PostgreSQL. Use the intended
development database; database writes were not run as part of this validation.
The API and durable observation worker remain separate processes. `RASTERIO`
uses bounded GDAL cache configuration in the raster reader; no per-request
source download is performed.

Example requests after a dataset is registered:

```text
GET /api/v1/terrain/coverage?latitude=-89.44&longitude=222.1
GET /api/v1/terrain/regions/shackleton-connecting-ridge/heightmap
```

Then submit `POST /api/v1/ephemeris/now` or
`POST /api/v1/ephemeris/timeline` with `horizon_mode: "terrain"`; poll the
returned job status URL and fetch the result URL. Terrain mode returns
`TERRAIN_UNAVAILABLE` (422) without usable registered coverage. A prepared
asset missing or unreadable after acceptance fails the durable job with
`TERRAIN_DATA_UNAVAILABLE` (503).

## Verification

Controlled test rasters and registry rows are used for deterministic tests;
they are not presented as NASA observations. On the real Product 90 asset, the
catalog Shackleton point returned `available: true`; its heightmap returned a
129 × 129 local ENU grid with 16,641 finite samples. A bounded horizon sample
at azimuth 90 degrees returned 1.761216 degrees at a 10 m radial sample step;
the observer surface sample was 1,952.356093 m. These are outputs from this
specific raster and implementation, not independent accuracy measurements.
Alembic reached `0003_stage4_terrain_registry`; registration returned
`lola-product-90-09b7ca80f9e6a146`. Deterministic verification ran Ruff,
format-check, `compileall`, 40 terrain tests, and 27 contract tests. One
`TestClient` runtime health test was deselected because Windows asyncio
socket-pair creation timed out in this environment. No database-writing
integration test against an isolated test database was run. Follow-up
read-only in-process route checks returned HTTP 200 for both coverage and
heightmap. A direct worker-function observation using live Horizons at
`2027-07-15T12:00:00Z` succeeded with the registered DEM; Sun elevation/horizon
were -1.088272° / 0.097070° and Earth elevation/horizon were -6.179106° /
1.506503°. Both visibility flags were false. A one-day timeline at 360-minute
resolution also succeeded with four points and returned zero sunlit, Earth
visible, and golden-window hours. These live calculations were not persisted as
jobs. A separate PostgreSQL integration test on a temporary isolated container
passed for terrain now and timeline job lifecycle, controlled Horizons fixtures,
result persistence, cache reuse, and observer altitude. Two existing isolated
PostgreSQL tests also passed for durable cache and lease fencing. The new test
uses a test-only controlled terrain service and registry row; its fixture values
are not used for operational requests. Durable job results were validated
against the API schemas.

Reproduce the database integration checks against a dedicated PostgreSQL test
database whose name ends in `_test`:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://test_user:test_password@127.0.0.1:5432/lunar_navigator_stage4_test"
.\.venv\Scripts\pytest.exe tests\test_stage1_postgres.py::test_terrain_observation_job_lifecycle_and_cache_on_postgresql -q -p no:cacheprovider
.\.venv\Scripts\pytest.exe tests\test_stage1_postgres.py::test_versioned_seed_and_durable_job_cache_on_postgresql tests\test_stage1_postgres.py::test_global_provider_slot_and_claim_fencing_on_postgresql -q -p no:cacheprovider
```

## Limitations

- Product 90 at 20 m cannot resolve smaller terrain features, and the horizon
  uses discrete ray samples. No independent real-site horizon measurement has
  been compared against the result.
- Horizon requests can fail when the complete required ray intersects the raster
  boundary or no-data cells; unavailable terrain is intentionally explicit.
- Only the cataloged Shackleton and Faustini points receive stable display-region
  IDs from the migration. Other supported points use coordinate-specific region
  IDs returned by the coverage endpoint.
- The display heightmap is a bounded rendering grid. Physical terrain visibility
  continues to use the source DEM and curved lunar geometry, not this grid.
