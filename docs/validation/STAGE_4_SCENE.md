# Stage 4 Local Terrain Visualization & Scene Validation

## Overview

Stage 4 implements the 3D local lunar terrain visualization in the observation
workspace. It loads numerical elevation data from the backend heightmap endpoint,
constructs a local 3D surface mesh using strict East-North-Up (ENU) coordinate
conventions, places the observer on the reconstructed local terrain surface, and
displays terrain-aware direction vectors and horizon thresholds.

The implementation strictly maintains that **backend visibility calculations are
authoritative**. Visual rendering features (such as Three.js mesh facets and GPU
shadows) serve as visual reference aids only; they never determine or override
communication, power, or golden-window states.

---

## 1. Numerical Heightmap Ingestion & Validation

The heightmap client (`ApiClient.getHeightmap`) and validator (`validateHeightmap`
in `frontend/src/features/scene/terrainMesh.ts`) enforce the schema specified in
`contracts/openapi.v1.yaml`:

- **Coordinate Frame:** Must be explicitly `frame: "local_enu"`. Non-ENU frames
  or unreferenced datums are rejected.
- **Dimensions & Grid Spacing:** `width` and `height` must be positive integers
  $\ge 2$. `spacing_m` must be a positive finite number ($> 0$).
- **Elevation Array:** `elevation_m` must have length exactly equal to
  $\text{width} \times \text{height}$, with every element being a finite number.
  Any `NaN`, `Infinity`, or length mismatch triggers immediate validation failure.
- **Origin Reference:** The `origin` object must provide finite `latitude`,
  `longitude`, and `elevation_m` (lunar reference sphere datum).
- **No Pseudo-Terrain:** Texture brightness, hillshade imagery, and bump maps
  are never interpreted as physical elevation data.

---

## 2. 3D Terrain Mesh Construction & Orientation

The local surface geometry is built via `buildTerrainGeometry`:

- **Row and Column Ordering:**
  - Row index $r \in [0, \text{height}-1]$ corresponds to north:
    $\text{north} = \text{north\_min\_m} + r \cdot \text{spacing\_m}$
  - Column index $c \in [0, \text{width}-1]$ corresponds to east:
    $\text{east} = \text{east\_min\_m} + c \cdot \text{spacing\_m}$
  - Flat array index: $i = r \cdot \text{width} + c$
- **Three.js Scene Coordinate Mapping:**
  $$\text{scene.x} = \text{east} \cdot s$$
  $$\text{scene.y} = \text{up} \cdot s \cdot v_{\text{exag}}$$
  $$\text{scene.z} = -\text{north} \cdot s$$
  where $s = 12.0 / \max(\text{span}_{\text{east}}, \text{span}_{\text{north}})$ is
  the uniform physical scale factor, and $v_{\text{exag}}$ is the visual vertical
  exaggeration factor (defaulting to physical $1.0\times$).
- **Scale Consistency:** A single uniform scale factor is applied to both
  horizontal and vertical coordinates, preserving real aspect ratios and slopes.
  Any optional visual vertical exaggeration is explicitly labelled in the UI
  and defaults to $1.0\times$ (physical scale).
- **Surface Normals:** Computed from actual facet vertex positions via
  `geometry.computeVertexNormals()`.

---

## 3. Observer Placement & Direction Display

- **Local Surface Elevation:** At the local origin $(\text{east} = 0, \text{north} = 0)$,
  surface elevation $y_{\text{surface}}$ is computed via bilinear interpolation of the
  four surrounding grid nodes (`getLocalSurfaceElevationAtOrigin`).
- **Observer Height:** The observer marker and vantage point are placed at:
  $$(x, y, z) = (0,\; (y_{\text{surface}} + h_{\text{obs}}) \cdot s,\; 0)$$
  where $h_{\text{obs}}$ is the observer height in metres from the observation parameters.
- **Direction Vectors:** Sun and Earth direction vectors use the authoritative
  `direction_enu` unit vectors returned by the backend ephemeris service,
  converted to Three.js coordinates via `enuToLocalScene`:
  $$\text{scene.x} = \text{east},\quad \text{scene.y} = \text{up},\quad \text{scene.z} = -\text{north}$$
  Bodies are never shifted or perturbed to force visual agreement with display geometry.
- **Horizon Elevation Overlay:** The HUD displays both the body elevation angle
  and the returned terrain horizon threshold:
  `Sun: Az 180.0° · El 2.5° (Hrz 1.2°) (Visible)`

---

## 4. Separation of Visual Aids and Authoritative Science

- **Authoritative Backend Flags:** Sunlight, Earth visibility, and golden-window
  determinations are strictly governed by the backend response payload (`visible: true/false`).
- **GPU Shadows as Visual Aids:** WebGL directional shadows and surface facets
  provide visual context only. A shadow cast on the screen never toggles power or
  communication status.
- **Display Simplification:** If a coarse grid is displayed, the UI footer
  explicitly informs the operator:
  `Terrain Mesh: {dataset_id} · Res: {spacing_m}m · Model: {model_version} · Backend visibility authoritative · GPU shadows are visual aids only`.

---

## 5. Lifecycle, Caching & Error Isolation

- **In-Memory Caching:** `useHeightmap(regionId)` caches fetched heightmaps by
  `region_id` to eliminate redundant network roundtrips during timeline playback.
- **Timeline Playback Independence:** Scrubbing the sample slider, stepping
  frames, or running automated playback updates only the sample index and direction
  vectors; it does not trigger heightmap refetches.
- **Site & Dataset Transitions:** When the operator selects a different site or
  dataset, previous terrain meshes are immediately cleared, preventing old terrain
  from being misattributed to a new coordinate.
- **Graceful Display Error Handling:** If the heightmap endpoint returns 404, fails network
  validation, or encounters a WebGL context loss:
  1. An amber notice (`scene-terrain-error-notice`) displays the failure cause.
  2. The scene uses a local geometric reference surface for display
     (`GeometricHorizonReference`) when the numerical display mesh is unavailable.
     This visual fallback does not change the selected API horizon mode or its
     returned visibility values.
  3. All forms, charts, tables, and numeric outputs remain fully interactive and isolated
     inside the enclosing `SceneErrorBoundary`.

---

## 6. Verification & Test Suite

The Stage 4 terrain visualization suite was executed and validated:

```powershell
cd frontend
npm.cmd run lint
npm.cmd run check:api
npm.cmd test -- --testTimeout=10000
npm.cmd run build
```

### Results Summary

- **Linter (oxlint):** 53 files inspected; 0 errors, 0 warnings.
- **TypeScript & Vite Build (`tsc -b && vite build`):** Clean compilation, 56 modules transformed, production assets generated successfully.
- **Test Suite (Vitest):** 14 test suites, 167 unit/integration tests passed at the recorded run.
  - `terrainMesh.test.ts` (12 tests):
    - Rejection of invalid frames, negative spacing, and mismatched array lengths.
    - Detection and rejection of `NaN` and `Infinity` elevation values.
    - Row-major grid ordering and index mapping verification.
    - Local ENU axis sign mapping: $x = \text{east}$, $y = \text{up}$, $z = -\text{north}$.
    - Consistent horizontal and vertical physical scaling.
    - Bilinear surface elevation interpolation at $(0, 0)$.
    - Explicit vertical exaggeration scaling.
  - `useHeightmap.test.ts` (4 tests):
    - In-memory cache deduplication.
    - Immediate cache eviction and mesh clearing on region ID change.
    - Robust error propagation on network failure with manual retry support.
    - Null/undefined region ID handling.
  - `Scene.test.tsx`:
    - Terrain mesh rendering with provenance metadata.
    - Observer elevation above local interpolated surface.
    - Dynamic HUD horizon threshold display (`Hrz {deg}°`).
    - Display error handling without changing the selected API horizon mode.
    - Loading overlay during asset transfer.
    - Error isolation via `SceneErrorBoundary`.
  - `App.test.tsx`:
    - Full end-to-end workspace integration with catalog selection, timeline scrubbing, and scene synchronization.
