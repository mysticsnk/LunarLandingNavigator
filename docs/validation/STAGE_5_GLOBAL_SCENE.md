# Stage 5 Global Moon & Local Terrain Visualization Validation

## Overview

Stage 5 implements the dominant 3D spherical global Moon viewport and its deep
integration with the local terrain inspector, shared scenario state, and ephemeris
visibility results.

Key principles enforced:
1. **Full Spherical Representation:** The complete spherical Moon is rendered in the
   Moon-Centered Moon-Fixed (MCMF) Cartesian frame without mandatory cropping.
2. **Authoritative Science:** Backend visibility flags (`earth.visible: true/false`)
   are strictly authoritative. Communication links and travelling signal pulses are
   governed solely by the backend ephemeris result, never by visual ray-casts or screen geometry.
3. **True Coordinate Transformations:** Local topocentric ENU direction vectors are converted
   to global Moon-fixed Cartesian directions via rigorous rotational transforms (`enuToMoonFixed`),
   never reused directly as global vectors or animated with arbitrary sine formulas.
4. **Deliberate Far-Side Handling:** Markers on the back/far-side hemisphere are identified
   geometrically and rendered with subtle translucent opacity. Coordinates are never altered to
   force markers onto the visible hemisphere.
5. **Bundled Global Texture:** The checked-in NASA color map is loaded locally, so globe rendering does not depend on an upstream image request. The map is display imagery, not terrain elevation or scientific calculation input.

---

## 1. Global Moon Coordinate Systems

### 1.1 MCMF Basis at Surface Coordinate $(\phi, \lambda)$

Given latitude $\phi$ and normalized longitude $\lambda \in [-180, 180)$:

$$\hat{u}_{\text{east}} = [-\sin\lambda,\; \cos\lambda,\; 0]^T$$
$$\hat{u}_{\text{north}} = [-\sin\phi \cos\lambda,\; -\sin\phi \sin\lambda,\; \cos\phi]^T$$
$$\hat{u}_{\text{up}} = [\cos\phi \cos\lambda,\; \cos\phi \sin\lambda,\; \sin\phi]^T$$

This orthonormal basis maps topocentric direction $\vec{v}_{\text{enu}} = [E, N, U]^T$ to MCMF:

$$\vec{v}_{\text{mcmf}} = E \cdot \hat{u}_{\text{east}} + N \cdot \hat{u}_{\text{north}} + U \cdot \hat{u}_{\text{up}}$$

### 1.2 Global Three.js Scene Mapping

To align the Moon's rotation axis (+Z in MCMF) naturally with Three.js camera Up (+Y):

$$\text{scene.x} = +\vec{v}_{\text{mcmf}, x}$$
$$\text{scene.y} = +\vec{v}_{\text{mcmf}, z} \quad (\text{North Pole at }+Y)$$
$$\text{scene.z} = -\vec{v}_{\text{mcmf}, y} \quad (90^\circ\text{E at }-Z)$$

This constitutes a right-handed Cartesian frame where:
- $(0^\circ, 0^\circ)$ lies at $+X$
- $+90^\circ$ (North Pole) lies at $+Y$
- $-90^\circ$ (South Pole) lies at $-Y$
- $90^\circ\text{E}$ lies at $-Z$
- $180^\circ$ (Far side) lies at $-X$
- $90^\circ\text{W}$ (-90°) lies at $+Z$

---

## 2. Interactive Features & Camera Controls

- **Orbit Controls:** Smooth orbital rotation and zoom damping ($r_{\min} = 3.2$, $r_{\max} = 22.0$).
- **Viewpoint Presets:**
  - `Reset`: Returns to default oblique vantage $[3.5, 2.2, 6.0]$.
  - `South Pole`: Centers on the Artemis exploration zone at $-90^\circ$ latitude.
  - `Near Side`: Views the prime meridian facing Earth ($0^\circ$ lon).
  - `Far Side`: Views the lunar farside ($180^\circ$ lon).
- **Site Markers:**
  - Catalog sites rendered at true spherical surface coordinates.
  - Selected site highlighted with gold target ring and HUD label.
  - Back-facing (far-side) markers identified via $\hat{n} \cdot \vec{v}_{\text{camera}} < 0$ and styled translucently without coordinate shifting.
  - Clicking on any marker or the globe surface triggers synchronized selection callbacks to the shared application state.

---

## 3. Communication Link Specification (Task 3)

The communication line connects the Earth representation to the selected lunar site:

| Backend State | Line Appearance | Signal Pulses | HUD Status |
| :--- | :--- | :--- | :--- |
| `earth.visible === true` | Continuous glowing cyan (`#00f0ff`), opacity 0.85 | Travelling white pulses Earth $\to$ Moon | `Earth Link: Active (Line of sight open)` |
| `earth.visible === false` | Inactive dashed gray (`#666666`), opacity 0.45 | Pulses disabled / stopped | `Earth Link: Blocked (No line of sight)` |
| `isLoading` or no ephemeris | Line omitted | Pulses disabled | `Link: Awaiting ephemeris…` |

---

## 4. Workstation Layout & Synchronization (Tasks 4 & 5)

- **Layout Modes:**
  - `split` (default): Side-by-side dominant Global Moon and Local Terrain inspector.
  - `enlarge-global`: Global Moon expands across full workstation width with local terrain preserved below.
  - `enlarge-local`: Local Terrain inspector expands across full workstation width with global view preserved above.
- **Comparison Synchronization:** Selecting "Open timeline" on any ranked scenario updates the shared draft, synchronizing site coordinates, ephemeris vectors, and terrain mesh across both scenes.
- **Resilience:** Both viewports are independently wrapped in `SceneErrorBoundary` to ensure WebGL context losses remain localized.

---

---

## 5. Scene Diagnosis & Image 1 vs Image 2 Resolution (Task 1)

### 5.1 Diagnostic Findings for Image 1 (Current Schematic Scene)
Inspection of the initial workspace state shown in **Image 1** revealed five interrelated root causes:
1. **Component Role Inversion & Missing Globe Mount:**
   The primary card was hosting `LunarScene` (the local topocentric ENU scene) rather than `GlobalMoonScene`. When no numerical heightmap DEM was loaded, `LunarScene` rendered schematic axes (RGB) and a circular geometric horizon ring on an empty canvas.
2. **CSS Grid Breakdown in `App.css`:**
   At line 17 of `App.css`, Sasha's 3-column workstation layout defined `.grid-content, .visual-grid { display: contents; }` with `grid-template-areas: 'controls global local' 'controls bottom bottom'`. However, lines 226–231 re-declared `.visual-grid { display: grid; grid-template-columns: 1fr 1fr; }`. This override pushed the entire grid into the `global` column, squished both viewports to 340px, and left the `local` area vacant.
3. **Unobserved Globe Illumination:**
   Before an observation is computed, `sunPos` is `null`. Without dedicated neutral studio lighting, standard `MeshStandardMaterial` rendered completely black against the dark background.
4. **Coordinate Grid & Lunar Reference Markings:**
   The initial procedural texture was schematic. It has been replaced with the complete NASA global color map; coordinate grid lines are not currently overlaid on the globe.
5. **Secondary Panel Integration:**
   In Image 2, the right panel houses both the `Site Inspector` (live/cached metadata) and the `Local Terrain` preview (`LunarScene`). When no DEM is available, an explicit unavailable notice is displayed without replacing the global 3D Moon.

### 5.2 Resolution Implemented
- In `App.css`, restored `.visual-grid { display: contents; }` so `.visual-card:first-child` occupies `grid-area: global` (dominant viewport) and `.visual-card:nth-child(2)` occupies `grid-area: local`.
- In `GlobalMoonScene.tsx`, added neutral studio lighting (`ambientLight 0.65` + key directional light + fill light) active whenever `!sunPos`, switching seamlessly to the physical solar beam when ephemeris is available.
- The global color imagery is packaged locally and rendered as sRGB; it is not used as elevation data.
- Added `Focus Site` camera preset, selected site callout badge, and navigation instruction legend matching Image 2 (`CLICK: PIN | DRAG: ROTATE | SCROLL: ZOOM | DOUBLE-CLICK: RECENTER`).
- In `ObservationWorkspace.tsx`, added `Site Inspector` summary metrics above `LunarScene`, and wrapped 2D map layers in a collapsible drawer.

---

## 6. Verification Results

Run from `frontend/`:

```powershell
npm.cmd run check:api
npm.cmd run typecheck
npm.cmd run lint
npm.cmd test -- --run
npm.cmd run build
```

- **OpenAPI Schema Check (`check:api`):** Synchronized with `contracts/openapi.v1.yaml`.
- **TypeScript (`typecheck`):** Clean compilation, 0 type errors.
- **Linter (`oxlint`):** 57 files inspected; 0 errors, 0 warnings.
- **Test Suite (`vitest`):** 16 test files, **200 of 200 tests passed** (100% pass rate).
  - `coordinates.test.ts` (39 tests): MCMF basis transformations, reversible ENU-to-MoonFixed mapping, high-latitude mapping (-89.44° Shackleton), and longitude normalization (222.1° $\to$ -137.9°).
  - `GlobalMoonScene.test.tsx` (10 tests): Camera presets (Reset, Focus Site, South Pole, Near Side, Far Side), site marker interaction, high-latitude mapping, Sun/Earth directions, and communication line states (active, blocked, loading).
  - `Scene.test.tsx` (21 tests): Local ENU scene, WebGL error boundary isolation, heightmap mesh rendering, horizon elevation thresholds, and explicit terrain-unavailable notice.
  - `App.test.tsx` (19 tests): Full workspace regression including timeline scrubbing, comparison ranking, and map layer integration.
- **Production Build (`vite build`):** Clean build, assets compiled into `dist/`.
