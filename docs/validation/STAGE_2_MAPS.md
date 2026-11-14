# Stage 2 map validation

Date: 2026-11-14

This validation checks the registered map services and the Stage 2 coordinate
path. It does not validate terrain horizons or replace the agreed API contract.
No standalone shared Stage 2 control-case data file is defined. The deterministic
control uses the project input `222.1°E` example and catalog Shackleton coordinate;
the observation workflow cases are recorded in
`backend/tests/test_stage2_observation_workflow.py`.

## Registered layers and source evidence

| Layer ID | Provider and service | CRS and units | Registered extent | Request grid and image | Attribution and source |
| --- | --- | --- | --- | --- | --- |
| `LRO_WAC_Mosaic_Global_303ppd_v02` | Moon Trek WMTS | `urn:ogc:def:crs:EPSG::104903`, degrees | `[-180, -90, 180, 90]` | `default028mm`; global top-left `[-180, 90]`; matrix 8 is 512 columns by 256 rows, each 256 × 256; JPEG | NASA/GSFC/ASU LROC Team; tiles served by NASA/JPL Moon Trek. [Capabilities](https://trek.nasa.gov/tiles/Moon/EQ/LRO_WAC_Mosaic_Global_303ppd_v02/1.0.0/WMTSCapabilities.xml), [official WMTS guide](https://trek.nasa.gov/tiles/apidoc/trekAPI.html?body=moon) |
| `luna_wac_global` | LROC Lunaserv WMS 1.1.1 | `IAU2000:30100`, degrees | `[-180, -90, 180, 90]` | `SRS=IAU2000:30100`; BBOX is longitude,latitude x/y; `image/png` | NASA/GSFC/ASU LROC Team. [GetCapabilities](https://wms.im-ldi.com/?SERVICE=WMS&REQUEST=GetCapabilities&VERSION=1.1.1) |
| `luna_wac_roi_south_summer` | LROC Lunaserv WMS 1.1.1 | `IAU2000:30100`, degrees | `[-180, -90, 180, -45]` | `SRS=IAU2000:30100`; BBOX is longitude,latitude x/y; `image/png` | NASA/GSFC/ASU LROC Team; cite Speyerer and Robinson (2013) as recorded by the service. [GetCapabilities](https://wms.im-ldi.com/?SERVICE=WMS&REQUEST=GetCapabilities&VERSION=1.1.1), [official 100 m product metadata](https://data.lroc.im-ldi.com/lroc/view_rdr_product/WAC_ROI_SOUTH_SUMMER_100M) |

The LROC WMS capabilities give the south-summer layer a broad geographic bbox
through 90°N. The official product metadata instead reports a true latitude
range of 90°S to 45°S. The API registry now uses that product footprint envelope
so a request north of 45°S is rejected before contacting the WMS. It is an
envelope, not a pixel-level completeness mask; small no-data gaps inside it are
not described by the current layer contract.

The WMTS keeps the CRS string exactly as advertised. It is a lunar map CRS, not
Earth `EPSG:4326` or `EPSG:3857`. LROC uses its registered lunar `IAU2000:30100`
CRS. WMS 1.1.1 sends coordinates as x/y (longitude, latitude) and uses `SRS`,
not the WMS 1.3.0 `CRS` parameter.

## Coordinate and image alignment

The project catalog stores Shackleton Connecting Ridge as latitude `-89.44°`,
longitude `-137.9°`. The API accepts positive-east longitude `222.1°` and
normalizes it to the same `-137.9°` value. Existing backend and frontend checks
cover this normalization; the new map-service test also checks wrap behavior at
`359.9°` and `180°`.

The frontend places the marker in its equirectangular 360 × 180 degree view box
at `x = normalized_longitude + 180 = 42.1` and `y = 90 - latitude = 179.44`.
The corresponding level-8 Moon Trek tile is row `255`, column `59`: the saved
capabilities top-left is `[-180, 90]`, rows proceed south, and columns proceed
east. The WMS request uses the same normalized point in its longitude/latitude
BBOX. At the exact pole longitude is geographically singular; the 2D marker's
x-position follows the supplied longitude and should not be interpreted as a
different physical point.

### Bounded live image checks

All requests below used the registered HTTPS hosts, an 8-second timeout, and
small images. No files were added to the repository.

| Check | Request | Result |
| --- | --- | --- |
| Moon Trek tile used by the current map preview | Matrix 0, row 0, column 0 | HTTP 200, `image/jpeg`, 49,475 bytes |
| Moon Trek at Shackleton Connecting Ridge | Matrix 8, row 255, column 59 | HTTP 200, `image/jpeg`, 9,696 bytes |
| LROC global over the exact same geographic tile bounds | `BBOX=-138.515625,-90,-137.8125,-89.296875`, 256 × 256 | HTTP 200, `image/png`, 3,452 bytes |
| LROC south-summer mosaic containing the catalog point | `BBOX=-138.15,-89.65,-137.65,-89.25`, 512 × 410 | HTTP 200, `image/png`, 6,869 bytes |
| Named-feature check at the IAU Shackleton crater center | Matrix 8 row 255 column 440 and the matching LROC global WMS bounds | Both HTTP 200; the local crop is mostly shadow and does not visibly resolve the named crater boundary |

For the two global WAC images, a pixel-luminance comparison on identical
256 × 256 geographic bounds gave Pearson correlation `0.9729` without a flip.
In a 32 × 32 patch centered on the catalog point (approximately pixel 224, 52),
the no-flip correlation was `0.9442`; horizontal flip was `0.8761`. This supports
the same north-up, west-left placement for these two WAC layers at the selected
coordinate. It is not a named-crater identification: the polar WAC image there
is low contrast, and the separate Shackleton-center crop was too shadowed to
use as an identifiable visual landmark. A pixel-level named-feature check
remains incomplete.

The [USGS/IAU Shackleton gazetteer entry](https://planetarynames.wr.usgs.gov/Feature/5450)
provides an independent named-feature reference: Shackleton crater center
`(-89.67°, 129.78°)` in its listed planetographic, positive-east control
network, with an approximate boundary. The request for the corresponding
Moon Trek/LROC level-8 tile (row 255, column 440) succeeded, but both local
images were mostly shadow, so the crater outline could not be used to validate
its pixel position. This reference is not the project marker: the catalog point
is a connecting-ridge candidate, not the crater center. A site-specific
QuickMap link is not present in the site catalog (`quickmap_url` is null). The
verified [QuickMap application](https://quickmap.lroc.im-ldi.com/) can be opened
and searched for “Connecting Ridge”. The [official QuickMap update](https://lroc.im-ldi.com/images/1153)
documents short URLs for saving custom views, but the URL parameter format was
not verified here. The computer-use inventory had no browser session and
reported that the browser access host was unavailable, so an official UI
permalink could not be generated in this run. The frontend test currently labels a hand-written
`?extent=-89.5,221,-89.3,223` URL as verified; no official source checked for
this work documents that parameter, so it must not be used as a verified
site-specific link.

## Failure behavior and terrain boundary

Deterministic map tests exercise:

- an out-of-footprint south-summer WMS bbox, rejected with `422 VALIDATION_ERROR` and reason `outside_layer_extent`;
- a missing WMTS tile, mapped to `404 HTTP_404`;
- an invalid layer, mapped to `404 HTTP_404`;
- timeout, mapped to `503 HTTP_503`, and malformed/non-image responses, mapped to `502 HTTP_502`;
- WMS CRS, axis order, BBOX, image dimensions, and attribution preservation.

These provider failures are controlled deterministic tests; no live provider
outage was induced during this validation.

The south-summer product envelope catches locations north of 45°S. The broad
LROC global layer remains global. Provider responses inside a registered
envelope can still contain dark or empty-looking imagery; the adapter cannot
reliably distinguish a valid all-shadow image from an undocumented no-data
image by pixel brightness. That distinction needs an authoritative provider
coverage mask or no-data signal before the UI can promise availability for
every pixel. Provider HTTP errors and malformed/non-image bodies are not
converted to blank successful images.

Terrain remains unavailable for observation calculations. The preserved
[`terrain-stage1-handoff.md`](../sources/terrain-stage1-handoff.md) manifest
identifies Product 78 site DEMs and the pole-spanning Product 90 DEM, but none
is processed into a validated physical horizon model. `horizon_mode="terrain"`
continues to return `422 TERRAIN_UNAVAILABLE`; geometric Stage 2 observations
must not be described as terrain-aware.

## Frontend integration notes for Slavik

- `frontend/src/features/map/layers.ts` still mirrors the old global extent for
  `luna_wac_roi_south_summer`. The integrated workspace fetches registry
  metadata, but the local fallback must be aligned with the API extent.
- `frontend/src/features/map/LunarMap.test.tsx` treats an undocumented QuickMap
  `extent` query as verified. Replace it only after obtaining and checking a
  permalink generated by the official QuickMap UI.
- The current equirectangular marker math is consistent for the selected
  `-89.44°, -137.9°` location. Coverage warnings follow the registry envelope;
  they cannot identify internal image gaps until the provider supplies a tighter
  coverage/no-data signal.

## Reproduction

From the repository root in PowerShell:

```powershell
Push-Location backend
.venv/Scripts/ruff.exe check tests/test_map_services.py
.venv/Scripts/python.exe -m pytest tests/test_map_services.py tests/test_stage1_jobs.py -p no:cacheprovider
Pop-Location

Push-Location frontend
npm.cmd run test -- src/lib/coordinates.test.ts src/features/map/LunarMap.test.tsx
Pop-Location
```

For live reproduction, request the Moon Trek tile
`https://trek.nasa.gov/tiles/Moon/EQ/LRO_WAC_Mosaic_Global_303ppd_v02/1.0.0//default/default028mm/8/255/59.jpg`
and the LROC global WMS image at
`https://wms.im-ldi.com/?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=luna_wac_global&STYLES=&SRS=IAU2000%3A30100&BBOX=-138.515625%2C-90%2C-137.8125%2C-89.296875&WIDTH=256&HEIGHT=256&FORMAT=image%2Fpng`.
In PowerShell, run these two requests (the URLs are the exact checked requests):

```powershell
curl.exe --max-time 8 --fail --silent --show-error --write-out "%{http_code} %{content_type} %{size_download}\n" --output "$env:TEMP\moon_trek.jpg" "https://trek.nasa.gov/tiles/Moon/EQ/LRO_WAC_Mosaic_Global_303ppd_v02/1.0.0//default/default028mm/8/255/59.jpg"
curl.exe --max-time 8 --fail --silent --show-error --write-out "%{http_code} %{content_type} %{size_download}\n" --output "$env:TEMP\lroc_global.png" "https://wms.im-ldi.com/?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=luna_wac_global&STYLES=&SRS=IAU2000%3A30100&BBOX=-138.515625%2C-90%2C-137.8125%2C-89.296875&WIDTH=256&HEIGHT=256&FORMAT=image%2Fpng"
```

Both images use the same geographic pixel bounds; compare them without flipping
either image and calculate pixel luminance correlation over the full image and
the 32 × 32 neighborhood centered near pixel (224, 52). Do not download or
commit any source mosaics or DEMs for this validation.
