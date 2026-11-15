# Stage 5 Comparison Acceptance Report

**Scope:** Independent acceptance oracle, contract and terrain-provenance
review. No comparison production code or frontend components were changed.

## Result

**Stage 5 comparison acceptance is blocked.** The API contract reserves
`POST /api/v1/ephemeris/compare`, but OpenAPI marks it `planned`, the runtime
does not register it, and the worker only executes `now` and `timeline` jobs.
An existing backend route test confirms that a compare submission currently
returns 404. Therefore no runtime ranking, comparison job/result flow, provider
failure handling, or comparison UI behavior can be reported as passed.

## Acceptance cases prepared

[`STAGE_5_TEST_CASES.md`](STAGE_5_TEST_CASES.md) contains explicit, independently
calculated scores and expected ordering for:

- different catalog/custom sites at one start time;
- one catalog site at two start times;
- equivalent longitudes `222.1°` and `-137.9°` and an exact tie;
- supported-terrain and unsupported-terrain scenarios;
- exact and rounded-score ties;
- failure of one provider evaluation;
- a deterministic fixture cross-check against the timeline fixture.

These values are controlled acceptance expectations, not operational science
outputs. The current static fixtures establish one matching geometric
comparison/timeline summary pair with `development-fixture-v1`; they do not
substitute for live result-to-result validation.

## Results and blockers

| Area | Status | Evidence / blocker |
| --- | --- | --- |
| Contract and formula review | Reviewed | `docs/API_V1.md` section 11 and OpenAPI `ComparisonResult` specify v1 weights, unrounded-score ordering, longest-window tie-break, then request order. |
| Comparison API and jobs | Not implemented | OpenAPI `x-implementation-status: planned`; runtime route is absent; `backend/app/worker.py` has no comparison branch. Existing `test_runtime_registers_current_routes` asserts 404 for compare. |
| Independent expected score cases | Prepared | Hand-calculated values and literal expected orders are in `STAGE_5_TEST_CASES.md`; no production rank function was copied into the oracle. |
| Longitude equivalence | Existing behavior verified by code/tests; Stage 5 fixture cross-check added | API normalization maps 222.1° to -137.9°. Existing map, terrain and job tests cover this normalization; the new acceptance test checks the comparison/timeline fixture coordinates. |
| Geometric summary cross-check | Fixture-only pass | `Synthetic A` in `contracts/examples/comparison-result.json` matches `timeline-two-golden-windows.json` for the same represented coordinate, period, step, horizon mode, observer height, model version and summary. The fixture values are explicitly synthetic. |
| Supported terrain comparison | Not run | Stage 4 handoff records Product 90 terrain readiness at Shackleton and Faustini and a real Shackleton terrain timeline. No comparison endpoint exists to execute a paired terrain comparison or verify its result metadata. |
| Unsupported terrain all-or-nothing behavior | Not run | Contract expectation is 422 `TERRAIN_UNAVAILABLE` before enqueue when coverage is known unavailable. No compare route exists to verify it. |
| Terrain provenance | Conflicting prior-stage records; contract limitation | [`STAGE_4_BACKEND.md`](STAGE_4_BACKEND.md) records Product 90 dataset ID, checksum, 20 m resolution, processing version, lunar frame and footprint, while [`STAGE_4_TERRAIN_MODEL.md`](STAGE_4_TERRAIN_MODEL.md) says no source raster was downloaded and terrain is unavailable. This turn did not inspect the local asset/database, so current terrain readiness is not independently confirmed. Separately, comparison schema has only one top-level dataset/model field, so per-scenario provenance across different datasets/versions is unrepresentable without an agreed contract extension. |
| Third terrain area | Not verified | Peak near Shackleton (Site07) has no agreed application coordinate. Product footprint alone does not prove valid surrounding samples for horizon calculations at a specific point. |
| Provider failure and completeness | Not run | Contract requires a failed comparison job and no partial successful ranking. Compare job execution is absent. |
| Frontend acceptance | Not run | `frontend/src/features` contains no comparison workspace. Rank/metric rendering, ties, scenario reopening, global marker, local terrain and communication-point behavior await Sasha and Slavik's UI integration. |

### Terrain provenance details from Stage 4 handoff

The Stage 4 backend report records the registered terrain source as NASA/GSFC
LOLA PGDA Product 90,
dataset `lola-product-90-09b7ca80f9e6a146`, file
`LDEM_80S_20MPP_ADJ.TIF`, Float32 numerical DEM, 20 m/pixel,
`lunar-south-polar-v1`, south polar stereographic metres, MOON_ME / JPL DE421,
and reference radius 1,737,400 m. The recorded full-file SHA-256 is
`09b7ca80f9e6a146f970225d18af72fc02787669b3ef51b888e347d2b6845649`. Product 90
metadata gives an 80°S–90°S footprint including the south pole. The backend
report says its asset/manifest are stored outside Git. However,
`STAGE_4_TERRAIN_MODEL.md` records an earlier state with no downloaded raster and
no physical terrain support. This acceptance pass did not inspect the local
asset/database or redownload/revalidate the multi-gigabyte file; reconcile the
handoffs before claiming current runtime support.

The required third candidate, Peak near Shackleton, is not currently a catalog
site and has no agreed exact coordinate here. Do not accept a terrain comparison
for it until a real coordinate is agreed and the coverage endpoint confirms
sufficient valid samples. Product 78's 5 m local products are not approved
physical sources while their vertical reference and complete horizon coverage
remain unresolved. A display mesh cannot replace the source DEM.

### Contract issue for terrain comparisons

`ComparisonResult.meta` is singular: one `model_version` and one
`terrain_dataset_id` cover the entire comparison. The Stage 5 acceptance task
requires preserving data differences when scenarios use different terrain
sources or model versions. Until the owner agrees a contract extension with
per-scenario provenance (or explicitly restricts terrain comparisons to a
single shared dataset/version), such comparisons must not be represented as
fully traceable. This report does not change the API contract.

## UI acceptance checklist

Pending integration. Sasha and Slavik should verify against the completed
backend result:

- backend rank, score and all summary metrics match exactly;
- each scenario shows its own date and horizon mode;
- exact/rounded ties are not presented as an unambiguous scientific winner;
- opening a scenario preserves the selected site's coordinates and original
  date, duration, step, horizon mode, observer height and visibility margin;
- the globe marker, local terrain and communication visualization point to the
  selected ranked scenario;
- terrain source/version and limitations are visible when relevant.

The comparison response does not echo every common request parameter in each
ranked scenario. The UI must retain the accepted comparison request context to
reopen a scenario without silently changing parameters.

## Checks executed

From `backend`, the acceptance and contract checks passed (39 passed, one
Starlette/AnyIO deprecation warning). The focused controlled terrain checks
passed (19 passed, one same deprecation warning). Ruff passed. The full backend
suite did not collect: `numpy` is missing while importing
`tests/test_terrain_raster.py` and `tests/test_terrain_registry.py`. Invoking the
documented `uv run` commands also failed because `uv` is not installed in this
shell; the repository's local virtual environment was used instead. No live
Horizons, comparison, database, or terrain-source calls were performed.

## Reproduction

From `backend` with the repository virtual environment:

```powershell
.\.venv\Scripts\pytest.exe -q -p no:cacheprovider tests/test_stage5_comparison_acceptance.py tests/test_contract.py tests/test_health.py::test_runtime_registers_current_routes
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\pytest.exe -q -p no:cacheprovider tests/test_terrain_horizon.py tests/test_terrain_visibility.py
```

The current compare-route absence can be reproduced with:

```powershell
.\.venv\Scripts\pytest.exe -q -p no:cacheprovider tests/test_health.py::test_runtime_registers_current_routes
```

Once the comparison route is implemented, connect the acceptance matrix to the
actual submit/status/result service with controlled provider responses, add the
per-scenario terrain provenance contract decision, and repeat the selected
timeline cross-checks using matching live model/dataset versions. Then perform
the UI review with Sasha and Slavik. Do not call Stage 5 accepted before those
checks pass.
