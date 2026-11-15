# Stage 4 Terrain Model Engineering Handoff

This is a model and integration handoff, not a claim that terrain is available
for production observations. The numerical grid and curved-surface horizon core
are implemented and tested with controlled data. No source raster was downloaded,
loaded, prepared, or validated for physical calculations in this work.

## Source and area assessment

The three agreed areas are Shackleton Connecting Ridge (Product 78 Site01),
Faustini Rim A (Product 78 LM7), and Peak near Shackleton (Product 78 Site07).
Their local products are high-resolution source candidates. Their footprints do
not establish sufficient surrounding coverage for a complete physical horizon.
The regional Product 90 LDEM is the source candidate for the horizon rays because
its published footprint runs from 80 degrees south through the south pole to
90 degrees south, covering the south pole and the three named south-polar areas.
Its 20 m/pixel resolution and 2,696,082,051-byte file size are recorded in the
Stage 1 source observations. The file itself was not downloaded here.

| Area | Product ID | Published version | Numeric format / resolution | Published footprint | Horizontal and vertical reference | Current status |
| --- | --- | --- | --- | --- | --- | --- |
| Shackleton Connecting Ridge | `Site01_final_adj_5mpp_surf.tif` | Not stated by provider | Float32 GeoTIFF, 5 m/pixel, 3,200 × 3,200; 40,980,810 bytes | Local Site01 bounds X [-19,000, -3,000] m, Y [-20,000, -4,000] m | South polar stereographic, MOON_ME/DE421; source Z in metres; source-specific radius/datum not stated on Product 78 page; observed no-data `nan` | Metadata/header previously inspected; checksum and pixel values not verified in this turn; local raster is not sufficient horizon coverage by itself |
| Faustini Rim A | `LM7_final_adj_5mpp_surf.tif` | Not stated by provider | Float32 GeoTIFF, 5 m/pixel, 4,000 × 4,000; 64,033,675 bytes | Local LM7 bounds X [54,000, 74,000] m, Y [-10,000, 10,000] m | South polar stereographic, MOON_ME/DE421; source Z in metres; source-specific radius/datum not stated on Product 78 page; observed no-data `nan` | Metadata/header previously inspected; checksum and pixel values not verified in this turn; local raster is not sufficient horizon coverage by itself |
| Peak near Shackleton | `Site07_final_adj_5mpp_surf.tif` | Not stated by provider | Float32 GeoTIFF, 5 m/pixel, 3,200 × 3,200; 40,980,808 bytes | Local Site07 bounds X [22,000, 38,000] m, Y [-28,000, -12,000] m | South polar stereographic, MOON_ME/DE421; source Z in metres; source-specific radius/datum not stated on Product 78 page; observed no-data `nan` | Metadata/header previously inspected; checksum and pixel values not verified in this turn; exact project catalog coordinate is not present |
| Regional coverage for all three areas | `LDEM_80S_20MPP_ADJ.TIF` | `ADJ` processing stem; no semantic version stated | Float32 Cloud Optimized GeoTIFF, 20 m/pixel, 30,400 × 30,400; 2,696,082,051 bytes | 80°S–90°S, explicitly includes the south pole | South polar stereographic X/Y metres, MOON_ME/DE421; surface-height values in metres; observed no-data `nan` | Metadata and a bounded header were verified in Stage 0; full file/checksum/pixels not inspected; only candidate for regional horizon coverage |

Product source pages: [PGDA Product 78](https://pgda.gsfc.nasa.gov/products/78),
[PGDA Product 90](https://pgda.gsfc.nasa.gov/products/90). Product 90 identifies
the regional file as an LDEM surface-height product and gives its south-polar
coverage and frame. The NASA [LOLA RDR SIS](https://science.nasa.gov/wp-content/uploads/2024/01/lola-rdrsis.pdf)
documents LOLA elevations relative to a 1,737.4 km sphere. The official
[NASA astrodynamics frame reference](https://ntrs.nasa.gov/api/citations/20220014814/downloads/NASA%20TP%2020220014814%20final.pdf)
also documents LRO polar-stereographic coordinates in the ME frame with a
1,737.4 km lunar radius. Product 78's own page does not state the local adjusted
files' exact vertical datum; those files remain excluded from physical use until
their product-specific readme/values are checked against this convention.

Source assignment is explicit: Product 90 is the proposed regional numerical
elevation input; Product 78 is optional local-resolution data after its datum and
footprint are checked. Registered Moon Trek/LROC imagery is display context only
and is never an elevation source.

The current repository records **no source checksums** because no product file
was downloaded or supplied for hashing. The preparation tool computes a SHA-256
digest for an acquired file and can compare it with a previously trusted digest.
When no prior digest is supplied, the computed hash is an identity fingerprint,
not an independent checksum verification. The tool checks expected byte size,
TIFF byte-order/version magic, and an optional pinned SHA-256. It deliberately
labels that result `source_size_and_tiff_signature_checked_not_horizon_ready`; it does not
parse DEM values or create a normalized horizon-ready raster. Product 90 downloads
are blocked by default because the source is about 2.70 GB.

## Coordinate and height model

The service uses the API's planetocentric latitude and positive-east longitude.
Longitude input follows `[-180, 360)` and is normalized to `[-180, 180)` without
rounding the internal calculation. The official south-polar stereographic
operation with longitude of origin 0 uses:

```text
rho = 2 * R * tan((90 degrees + latitude) / 2)
X = rho * sin(longitude)
Y = rho * cos(longitude)
R = 1,737,400 m
```

The formula follows the south-pole case in the
[IOGP/EPSG Guidance Note](https://www.iogp.org/wp-content/uploads/2019/09/373-07-02.pdf).
The projection uses the official lunar radius and the source frame MOON_ME / JPL
DE421; it is not an Earth CRS. `222.1°E` and `-137.9°` map to the same projected
point. At the exact pole longitude is singular in the map projection; the input
longitude still defines the local east/north basis used for observer directions.

`TerrainGrid` accepts a single-band numerical grid after a caller has established
its source metadata and normalized its no-data representation. It expects Float32
surface heights in metres relative to the 1,737,400 m sphere, rows north-to-south,
columns west-to-east, a projected upper-left outer edge, and `None` for no-data.
It bilinearly samples only when all non-zero-weight source cells are valid. It
does not fill gaps or infer a source CRS from image pixels. The raster loader and
Product 78 vertical-datum conversion are not implemented.

For a resolved coordinate, `TerrainHorizonService.observer_surface` returns the
sampled source elevation separately from observer height and the resulting
Moon-centered, Moon-fixed Cartesian observer position. The observer position is
`(R + surface_elevation_m + observer_height_m)` along the unit vector defined by
the selected planetocentric latitude/longitude. Display scene scaling is not
involved.

## Horizon service and coverage policy

`TerrainHorizonService(grid, latitude, longitude, observer_height_m=2.0)` exposes:

- `observer_surface`: resolved coordinates, source surface height, observer
  height, MCMF position, dataset ID, and model version.
- `horizon_elevation(azimuth_deg)`: returns the maximum apparent terrain
  elevation, requested azimuth, search extent, sample spacing, observer details,
  dataset/model IDs, and `support_status="supported"`.
- Unsupported observer/ray samples raise `TerrainCoverageError` with
  `reason="outside_coverage"` or `reason="no_data"`. Callers must map these to
  the agreed `TERRAIN_UNAVAILABLE` behavior; there is no geometric fallback.

The horizon compares terrain points with the actual observer position in MCMF
Cartesian coordinates, projects the line-of-sight vector into local ENU, and
computes its elevation with `atan2(up, horizontal)`. This accounts for lunar
curvature. It skips the first 1.5 projected cells to avoid treating the observer's
own raster cell as an obstruction. The default radial sample spacing is half the
source cell size; finer spacing is accepted up to that same maximum. A ray is
extended until the upper bound from the highest reported LOLA topography
(10,792 m above the reference sphere) can no longer exceed the best sampled
terrain angle. The bound comes from the published LOLA global topography
assessment ([Smith et al., 2017](https://repository.si.edu/server/api/core/bitstreams/0b0f9173-7b8a-4117-b5f3-33a46eb35b3e/content)).
If the dataset ends before that point, or any interpolation touches no-data, the
request fails as unavailable. This makes search length depend on the actual ray
and observed horizon rather than an arbitrary fixed radius.

The tests compare 500 m and 250 m ray steps across a broad controlled ridge; their
horizon results agree within 0.02°. This is a sampling convergence check for a
synthetic surface, not a claimed accuracy for a real 20 m LDEM. Narrower terrain
features, the source's effective resolution, vertical error, frame alignment, and
unobserved no-data remain material accuracy limits.

## Acquisition, readiness, and integration

Run from `backend` using the repository virtual environment. The destination is
outside Git by default (`%LOCALAPPDATA%/LunarLandingNavigator/terrain`). The tool
refuses repository paths and partial files:

```powershell
.\.venv\Scripts\python.exe tools\prepare_terrain.py Site01_final_adj_5mpp_surf.tif --download
.\.venv\Scripts\python.exe tools\prepare_terrain.py Site01_final_adj_5mpp_surf.tif --file "$env:LOCALAPPDATA\LunarLandingNavigator\terrain\Site01_final_adj_5mpp_surf.tif"
```

Use `--timeout 30` to set the bounded socket timeout. Supply `--sha256` only
when a digest has been established through a trusted independent verification.
The same `--file` verification step can inspect a manually downloaded regional
Product 90 file without the tool initiating a multi-gigabyte transfer.

The Stage 4 integration handoff is the Python interface in
[`backend/app/terrain`](../../backend/app/terrain/). A map/terrain loader must
produce a `TerrainSource` with trustworthy numerical samples and error reasons;
the observation worker then requests horizons for the actual returned body
azimuths and records the real dataset/model IDs. The observation service currently
does not call this module, API terrain requests continue to fail with
`TERRAIN_UNAVAILABLE`, and no `terrain_dataset_id` should be advertised yet.

No Denys or Yaroslav agent was active during this work, so this service interface
is a draft handoff and has not been jointly reviewed or integrated. The repo also
has no `docs/integration/STAGE_4_TERRAIN.md` handoff to extend.

## Verification completed and remaining work

- **Backend lint:** `ruff check .` passed.
- **Backend tests:** `pytest -q -p no:cacheprovider` completed with 327 passed
  and 14 skipped. The skips require explicit live Horizons or dedicated
  PostgreSQL settings; one existing Starlette/AnyIO deprecation warning appeared.
- **Terrain-focused tests:** 15 passed independently. No tests used a downloaded
  or live terrain raster.
- **Passed:** controlled projection/longitude equivalence, bilinear row
  orientation, no-data rejection, actual observer/surface height distinction,
  curved reference sphere, different observer heights, east/west ridge orientation,
  near/distant obstacle behavior, independent closed-form terrain geometry,
  radial-step convergence, unsupported coverage, and atomic source-file integrity
  tests.
- **Official metadata retrieved:** PGDA Product 78 and Product 90, NASA LOLA
  reference documentation, NASA's lunar frame reference, and the south-polar
  stereographic operation reference were accessible and support the provenance
  links above. Product 90 metadata confirms a numerical LDEM whose published
  footprint includes the south pole.
- **Not completed:** source raster download, real DEM pixel inspection, raster
  loading, prepared output creation, real-area horizon calculation, or comparison
  with an independent measurement from Product 90. The current environment has
  no `rasterio`, `GDAL`, or `tifffile` reader and Product 90 was not downloaded.
- **Not coordinated:** dependency/loader selection and the observation-worker
  handoff with Denys and Yaroslav. The service receives an already numerical
  `TerrainSource`; it does not yet load a PGDA GeoTIFF.

Reproduce deterministic checks:

```powershell
cd backend
.\.venv\Scripts\ruff.exe check app\terrain tools\prepare_terrain.py tests\test_terrain_horizon.py tests\test_terrain_preparation.py
.\.venv\Scripts\pytest.exe tests\test_terrain_horizon.py tests\test_terrain_preparation.py -q -p no:cacheprovider
```

Terrain is **not ready for physical observation calculations**. Before enabling
it, select and coordinate a GeoTIFF reader, verify each product's actual metadata
and vertical reference, load/check numerical samples and no-data, calculate the
usable ray footprint for every agreed site, test horizons against real terrain
features, and integrate this service without changing the API contract.
