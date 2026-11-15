# Stage 6 Rendering Asset Verification

## Global Moon color texture

Packaged `/assets/lroc_color_2k.jpg` from NASA's [CGI Moon Kit](https://svs.gsfc.nasa.gov/4720/). NASA describes the 2025 color map as adapted from the LROC WAC Hapke-normalized mosaic, with missing polar latitudes filled from the lower-resolution monochrome LRO Laser Altimeter Data Set (LDAM). The imagery is for display, not scientific analysis. Credit NASA's Scientific Visualization Studio; visualizer Ernie Wright; scientist Noah Petro (NASA/GSFC). The [official 2K JPEG](https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/lroc_color_2k.jpg) is 2048 by 1024 pixels. The checked-in file is 457,942 bytes (447.2 KiB) with SHA-256 `f7130a1822681fa7512d7dcfd40db8c10b9ba4f06777910348698260ed7a2170`.

This is a complete 2:1 global map, not a cropped regional image. NASA states the WAC source range is 70°N through 70°S and that lower-resolution LDAM albedo fills the omitted polar latitudes. NASA describes pixels as longitude/latitude samples and the map as centered on 0° longitude, but does not name a projection. The manifest records an equirectangular lon/lat mapping as an inference from those facts and the 2:1 image. Longitude wraps across 360°; use normalized positive-east longitude in `[-180, 180)`. Image rows are north at the top and south at the bottom; horizontal pixels progress west to east.

Expected Three.js mapping for the existing scene convention is `u=(normalized_longitude+180)/360`, `v=(90+latitude)/180`, with `TextureLoader`'s default `flipY=true`. This places 0° longitude at scene +X, 90°E at scene -Z, north at +Y, and south at -Y. `GlobalMoonScene` loads this asset as its sRGB color map and overlays a latitude/longitude graticule. The texture supplies color only: it does not provide global numerical relief or drive physical calculations. The local scene uses the separately returned API heightmap when coverage is available.

The inventory and exact file integrity are checked by `frontend/src/features/scene/lunarTextureAsset.test.ts`. NASA's page lists this image as 447.2 KB; the local exact size and hash above are measured from the downloaded JPEG.

## Local terrain delivery and provenance

No DEM or generated heightmap is stored in Git. Product 90 `LDEM_80S_20MPP_ADJ.TIF` is the registered regional numerical source documented by Stage 4: Float32 GeoTIFF, 30,400 by 30,400 samples, 20 m, south-polar stereographic X/Y metres, MOON_ME / JPL DE421, reference radius 1,737,400 m, NoData NaN, 2,696,082,051 bytes, SHA-256 `09b7ca80f9e6a146f970225d18af72fc02787669b3ef51b888e347d2b6845649`. The official [Product 90 metadata](https://pgda.gsfc.nasa.gov/products/90) identifies coverage from 80°S through the south pole. The source file belongs under `%LOCALAPPDATA%\LunarLandingNavigator\terrain`, outside this repository. Read the [Stage 4 backend handoff](STAGE_4_BACKEND.md) for its preparation and registration commands.

The frontend requests only the bounded display grid at `/api/v1/terrain/regions/{region_id}/heightmap`; it has no request for the original TIFF. `useHeightmap` caches the returned JSON in memory by region ID. The API contract defines `frame=local_enu`, row-major values (`row * width + column`), rows increasing north, columns increasing east, and scene axes `x=east`, `y=up`, `z=-north`. `elevation_m` is local up displacement from the scene origin; `origin.elevation_m` is the source surface elevation at the origin. It is distinct from the observer height supplied in observation parameters. Product IDs and dataset/model version values must stay attached to returned results.

| Area | Site/region handoff | Available evidence and limit |
| --- | --- | --- |
| Shackleton Connecting Ridge | Catalog region `shackleton-connecting-ridge`; `(-89.44°, -137.9°)` | Stage 4 reported a real Product 90 coverage check and a 129 by 129 grid at 20 m spacing. Not re-verified in this checkout because its local raster, database, and API are unavailable. |
| Faustini Rim A | Catalog region `faustini-rim-a`; `(-87.45°, 77.0°)` | Stage 4 reports source samples/readiness at this point; a current heightmap response was not re-verified here. |
| Peak near Shackleton (PGDA Site07) | Product 90 footprint includes the south-pole region; no stable named app region is established in this checkout. Resolve a supported coordinate through the coverage endpoint before requesting the grid. | Source footprint is not proof of the site's current sample support. Do not display a Shackleton or Faustini grid for this location. Product 78's local Site07 DEM is not the registered physical source. |

For the two named catalog points, run the following with the backend, database, and Product 90 registered. It verifies the actual returned origin and keeps the large JSON out of the terminal:

```powershell
$api = 'http://127.0.0.1:8000/api/v1'
$coverage = Invoke-RestMethod "$api/terrain/coverage?latitude=-89.44&longitude=222.1"
if (-not $coverage.available) { throw "Shackleton terrain unavailable: $($coverage.reason)" }
$grid = Invoke-RestMethod "$api/terrain/regions/$($coverage.region_id)/heightmap"
$grid | ConvertTo-Json -Depth 6 | Set-Content "$env:TEMP\shackleton-heightmap.json"
[pscustomobject]@{ region_id=$grid.region_id; dataset_id=$grid.dataset_id; model_version=$grid.model_version; frame=$grid.frame; origin=$grid.origin; width=$grid.width; height=$grid.height; spacing_m=$grid.spacing_m; sample_count=$grid.elevation_m.Count; source_url=$grid.source_url; attribution=$grid.attribution }
```

Use `latitude=-87.45&longitude=77.0` for Faustini. Require the returned origin to match the selected catalog coordinates (longitude normalized to `[-180,180)`), verify `sample_count -eq width*height`, and inspect the returned region/dataset/model IDs before attaching the grid to the local view. The exact selected region's heightmap is a local rendering asset; it is never the input for physical terrain visibility.

## Delivery checks and source display

The Vite development server and production preview served the JPEG at `/assets/lroc_color_2k.jpg` with HTTP 200, `image/jpeg`, and exactly 457,942 bytes. The preview also served the manifest as HTTP 200 `application/json`. The image response included ETag and `Cache-Control: no-cache`; this is Vite behavior, not a production CDN/cache policy. A nonexistent `.jpg` URL returned HTTP 200 `text/html` from the SPA fallback, so clients must validate image decoding and the production host should be checked for an asset-specific 404. A browser network panel was not available in this run, so client transfer measurements and visual marker alignment remain pending.

Code inspection confirms normal frontend terrain loading calls the heightmap API rather than fetching the 2.696 GB source DEM. The current working tree does not contain the Product 90 raster, the backend was not listening on `127.0.0.1:8000`, and so the live terrain response content type, cache headers, error envelope, and real display-grid bytes could not be inspected now. The heightmap route has no explicit cache header in its handler; the existing frontend cache lasts only for the page session. Record and test any later shared cache policy with the backend owner.

The global texture's attribution and projection/orientation notes are in `frontend/public/assets/manifest.json`; the scene uses the texture and renders the coordinate graticule. The local scene identifies dataset, resolution, model version, and display exaggeration, but does not render `heightmap.attribution` or `source_url`. Its unavailable state remains explicit and does not substitute an unrelated crater image.


The official [Moon Trek WMTS guide](https://trek.nasa.gov/tiles/apidoc/trekAPI.html?body=moon) opened and describes RESTful WMTS, GetCapabilities-driven identifiers, and the missing-tile/no-coverage behavior. In this run, the web reader rejected the XML capabilities content type and could not retrieve the LROC WMS capabilities request; those tool failures do not establish provider failure. The [QuickMap application](https://quickmap.lroc.im-ldi.com/) loaded its HTML shell, but the web reader reported that JavaScript must be enabled. The existing [Stage 2 map verification](STAGE_2_MAPS.md) documents the registered Moon Trek `LRO_WAC_Mosaic_Global_303ppd_v02` WMTS and LROC `luna_wac_global` / `luna_wac_roi_south_summer` WMS layers, including real tile/image checks and attribution. Those bounded tile/image checks are prior evidence and were not repeated during this asset-only run. The site catalog appropriately keeps site-specific `quickmap_url` null because UI permalink parameters have not been verified. Search by feature name (Connecting Ridge, Faustini, or Peak near Shackleton); do not invent URL parameters.

## Reproduction

Re-download and verify the official display texture from the repository root:

```powershell
New-Item -ItemType Directory -Force frontend\public\assets | Out-Null
curl.exe --fail --location --max-time 30 --output frontend\public\assets\lroc_color_2k.jpg https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/lroc_color_2k.jpg
Get-FileHash frontend\public\assets\lroc_color_2k.jpg -Algorithm SHA256
(Get-Item frontend\public\assets\lroc_color_2k.jpg).Length
$image = [System.Drawing.Image]::FromFile((Resolve-Path frontend\public\assets\lroc_color_2k.jpg))
"$($image.Width)x$($image.Height)"
$image.Dispose()
```

Run the asset test and production build from `frontend`:

```powershell
npm.cmd test -- src/features/scene/lunarTextureAsset.test.ts
npm.cmd run build
```

For the backend heightmap commands, provision Product 90 using `docs/validation/STAGE_4_BACKEND.md`, start the API and database, then execute the PowerShell coverage/grid snippet above. Normal app viewing must retrieve the bounded API grid only; never point the browser to the original DEM download URL.
