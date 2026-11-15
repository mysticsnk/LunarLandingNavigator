# Stage 5 Comparison Acceptance Report

## Current status

The comparison API, durable worker path, approved per-scenario provenance
extension, and frontend comparison flow are integrated. Current automated check
results and the remaining limits are recorded in
[`STAGE_5_BACKEND.md`](STAGE_5_BACKEND.md). This report does not claim a live
provider comparison or PostgreSQL integration run.

## Controlled acceptance cases

[`STAGE_5_TEST_CASES.md`](STAGE_5_TEST_CASES.md) contains explicit score and
ordering cases for mixed sites, separate dates, normalized longitudes, ties,
terrain availability, and provider failure. Those inputs are development/test
fixtures and are not operational lunar observations.

The comparison/timeline fixture cross-check verifies the shared represented
summary and per-scenario provenance. The fixture is explicitly synthetic; it
does not establish live comparison-to-timeline agreement.

## Terrain limits

Terrain comparisons resolve support for every scenario before enqueue and pin
dataset/model metadata per scenario. Automated tests with controlled terrain
do not establish the current readiness of local terrain assets or validate a
real paired terrain comparison. The Product 90 and Site07 notes in
[`STAGE_4_BACKEND.md`](STAGE_4_BACKEND.md) remain subject to the configured
manifest and coverage service.

The contract carries each ranked scenario's model, dataset, and sources.
`meta.terrain_dataset_id` is the shared dataset only when all scenarios use the
same dataset; it is null for mixed datasets and geometric comparisons.

## UI acceptance checklist

- Render backend rank, score, and summary values without client-side ranking.
- Preserve each scenario's date and common comparison settings when reopening it.
- Present equal scores as ties consistent with the returned ranking reason.
- Keep the global marker, local terrain, and communication visualization tied
  to the selected ranked scenario.
- Show terrain provenance and limitations when applicable.

Automated UI checks do not replace visual acceptance against a running backend.
