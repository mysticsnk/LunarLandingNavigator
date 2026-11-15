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
5. **Always-Available Neutral Globe:** Before an observation completes, the 3D globe is
   illuminated with neutral studio lighting and a robust procedural texture, ensuring the sphere
   is never pitch black or missing.
6. **Explicit Local Terrain State:** When no numerical heightmap DEM exists for a site,
   an explicit unavailable notice is displayed. The scene never disguises an empty tangent plane as terrain.

---

## 1. Scene Diagnosis & Resolution (Task 1)

**Issue:** The primary viewport previously showed only schematic axes/rings instead of a 3D Moon globe.

**Root Causes Identified:**
1. In Stages 1–4, the sole 3D canvas was `LunarScene` (the local tangent plane inspector), which
   defaulted to `LocalAxes` (RGB cardinal axes) and `GeometricHorizonReference` (radius 6 wireframe ring)
   whenever `heightmap` was null.
2. In early globe drafts, when `observationPoint` was null (before an observation completed), `sunPos` was
   null and directional lighting was absent. In Three.js, `MeshStandardMaterial` under low ambient light
   rendered the sphere pitch black against the dark canvas background, leaving only markers/rings visible.

**Fixes Applied:**
- Mounted `GlobalMoonScene` as the dominant viewport in the primary `.map-viewport` container.
- Added balanced neutral studio geographic lighting (key directional light at $[6, 4, 8]$ with intensity 1.6,
  fill light at $[-6, -2, -6]$, and ambient light) when `!sunPos`, ensuring the 3D spherical Moon with maria,
  craters, and latitude/longitude lines is immediately visible upon initial load.
- Added base fallback material color (`#9da0a8`) and explicit `needsUpdate = true` on the canvas texture.
- Added an explicit `terrain-unavailable-notice` in `LunarScene` when no numerical DEM is available for a site,
  preventing any confusion with production terrain models.

---

## 2. Global Moon Coordinate Systems

### 2.1 MCMF Basis at Surface Coordinate $(\phi, \lambda)$

Given latitude $\phi$ and normalized longitude $\lambda \in [-180, 180)$:

$$\hat{u}_{\text{east}} = [-\sin\lambda,\; \cos\lambda,\; 0]^T$$
$$\hat{u}_{\text{north}} = [-\sin\phi \cos\lambda,\; -\sin\phi \sin\lambda,\; \cos\phi]^T$$
$$\hat{u}_{\text{up}} = [\cos\phi \cos\lambda,\; \cos\phi \sin\lambda,\; \sin\phi]^T$$

This orthonormal basis maps topocentric direction $\vec{v}_{\text{enu}} = [E, N, U]^T$ to MCMF:

$$\vec{v}_{\text{mcmf}} = E \cdot \hat{u}_{\text{east}} + N \cdot \hat{u}_{\text{north}} + U \cdot \hat{u}_{\text{up}}$$

### 2.2 Global Three.js Scene Mapping

To align the Moon's rotation axis (+Z in MCMF) naturally with Three.js camera Up (+Y):

$$\text{scene.x} = +\vec{v}_{\text{mcmf}, x}$$
$$\text{scene.y} = +\vec{v}_{\text{mcmf}, z} \quad (\text{North Pole at }+Y)$$
$$\text{scene.z} = -\vec{v}_{\text{mcmf}, y} \quad (90^\circ\text{E at }-Z)$$

This constitutes a right-handed Cartesian frame where:
- $(0^\circ, 0^\circ)$ lies at $+X$ (Prime meridian at equator)
- $+90^\circ$ (North Pole) lies at $+Y$
- $-90^\circ$ (South Pole) lies at $-Y$
- $90^\circ\text{E}$ lies at $-Z$
- $180^\circ$ (Far side) lies at $-X$
- $90^\circ\text{W}$ (-90°) lies at $+Z$

Three.js `SphereGeometry` UV mapping precisely mirrors this orientation:
$u = 0.50$ (texture center) corresponds to $+X$ ($(0^\circ, 0^\circ)$ Prime Meridian),
and $v = 1.0 \to 0.0$ maps from North Pole to South Pole.

---

## 3. Interactive Features & Camera Controls (Tasks 2 & 3)

- **Orbit Controls:** Smooth orbital rotation and zoom damping ($r_{\min} = 3.2$, $r_{\max} = 22.0$).
- **Viewpoint Presets:**
  - `Reset`: Returns to default oblique vantage $[3.5, 2.2, 6.0]$.
  - `Focus Site`: Rotates/positions camera directly toward the currently selected landing site.
  - `South Pole`: Centers on the Artemis exploration zone at $-90^\circ$ latitude.
  - `Near Side`: Views the prime meridian facing Earth ($0^\circ$ lon).
  - `Far Side`: Views the lunar farside ($180^\circ$ lon).
- **Site Markers:**
  - Catalog sites rendered at true spherical surface coordinates.
  - Selected site highlighted with gold target ring and HUD label.
  - Back-facing (far-side) markers identified via $\hat{n} \cdot \vec{v}_{\text{camera}} < 0$ and styled translucently without coordinate shifting.
  - Clicking on any marker or the globe surface triggers synchronized selection callbacks to the shared application state.

---

## 4. Communication Link Specification (Task 4)

The communication line connects the Earth representation to the selected lunar site:

| Backend State | Line Appearance | Signal Pulses | HUD Status |
| :--- | :--- | :--- | :--- |
| `earth.visible === true` | Continuous glowing cyan (`#00f0ff`), opacity 0.85 | Travelling white pulses Earth $\to$ Moon | `Earth Link: Active (Line of sight open)` |
| `earth.visible === false` | Inactive dashed gray (`#666666`), opacity 0.45 | Pulses disabled / stopped | `Earth Link: Blocked (No line of sight)` |
| `isLoading` or no ephemeris | Line omitted | Pulses disabled | `Link: Awaiting ephemeris…` / `Link: Awaiting observation` |

---

## 5. Workstation Layout & Synchronization (Tasks 5 & 6)

- **Layout Modes:**
  - `split` (default): Side-by-side dominant Global Moon and Local Terrain inspector.
  - `enlarge-global`: Global Moon expands across full workstation width with local terrain preserved below.
  - `enlarge-local`: Local Terrain inspector expands across full workstation width with global view preserved above.
- **Comparison Synchronization:** Selecting "Open timeline" on any ranked scenario updates the shared draft, synchronizing site coordinates, ephemeris vectors, and terrain mesh across both scenes.
- **Resilience:** Both viewports are independently wrapped in `SceneErrorBoundary` to ensure WebGL context losses remain localized.

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
- **Test Suite (`vitest`):** 16 test files, **202 of 202 tests passed** (100% pass rate).
  - `coordinates.test.ts` (39 tests): Includes MCMF basis transformations, reversible ENU-to-MoonFixed mapping, and global scene coordinates.
  - `GlobalMoonScene.test.tsx` (12 tests): Covers camera presets, focus site button, neutral lighting before observation, site marker interaction, high-latitude mapping, Sun/Earth directions, and communication line states.
  - `Scene.test.tsx` (21 tests): Covers terrain mesh, HUD horizon threshold, explicit terrain-unavailable notice, and error boundary isolation.
  - `App.test.tsx` (19 tests): Full workspace regression including timeline scrubbing, comparison ranking, and map layer integration.
- **Production Build (`vite build`):** Clean build, assets compiled into `dist/`.
