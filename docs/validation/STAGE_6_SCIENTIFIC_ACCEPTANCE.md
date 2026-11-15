# Stage 6 Scientific Acceptance Report

**Date:** 2026-11-15
**Role:** Scientific Acceptance Engineer
**Status:** ACCEPTED (as recorded by the controlled verification run; this integration turn repeats only the checks listed in its completion report)
**Contract Version:** API v1 (`contracts/openapi.v1.yaml`)
**Ranking Version:** v1

---

## 1. Executive Summary

This scientific acceptance report evaluates the Stage 6 frontend and backend integration of the Lunar Landing Site Navigator. The redesigned workstation layout integrates:
- Compact top bar and activity rail;
- Left directory, search, catalog filtering, and scenario inputs;
- Dominant upper 3D spherical global Moon viewport with MCMF coordinates;
- Authoritative Earth communication link governed strictly by backend ephemeris results;
- Separate local terrain inspector rendering 1:1 numerical ENU heightmaps;
- Bottom timeline interval analysis, sample playback, and summary cards;
- Comparative multi-scenario ranking using the authoritative v1 formula.

All numerical and physical presentations were verified against authoritative API contract specifications and controlled acceptance oracles. No decorative or synthetic operational values were permitted.

---

## 2. Frozen Reference Scenarios (Task 1)

| ID | Category | Site / Coordinates | Period / UTC Time | Mode | Input Summary / Conditions | Expected Outcome | Verification Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **REF-01** | Single Observation | Shackleton Ridge (-89.44°, -137.9°) | `2027-07-15T12:00:00Z` | Geometric | H=2m, M=0° | Sun vis=true (el 1.25°), Earth vis=true (el 6.14°), Golden=true | **PASSED** |
| **REF-02** | Single Observation | Shackleton Ridge (-89.44°, -137.9°) | `2027-07-15T12:00:00Z` | Terrain | Product 90, H=2m, M=0° | Sun vis=false (DEM horizon 1.76° > el 1.25°), Earth vis=false, Golden=false | **PASSED** |
| **REF-03** | Timeline | Custom Shackleton (-89.44°, -137.9°) | `2027-07-15T00:00:00Z` + 1d | Geometric | Step=360 min, 4 samples | Sunlit=75% (18h), Earth=75% (18h), Golden=50% (12h), Longest=6h, 2 windows | **PASSED** |
| **REF-04** | Timeline | Faustini Rim A (-87.45°, 77.0°) | `2027-07-15T00:00:00Z` + 1d | Terrain | Product 90, Step=360 min | Sunlit=0% (0h), Earth=0% (0h), Golden=0% (0h), Longest=0h, 0 windows | **PASSED** |
| **REF-05** | Comparison | Synthetic A vs Synthetic B | `2027-07-15T00:00:00Z` + 1d | Geometric | A: S=75, E=75, G=50; B: S=50, E=50, G=25 | Score A=67.5 (Rank 1), Score B=42.5 (Rank 2). Unrounded score ordering | **PASSED** |
| **REF-06** | Comparison Tie (Window) | Short Window vs Long Window | `2027-07-15T00:00:00Z` + 1d | Geometric | Both score 65.0; Short=4h, Long=10h | Long Window ranks #1 based on longest golden window tie-breaker | **PASSED** |
| **REF-07** | Comparison Tie (Order) | Scenario Alpha vs Scenario Beta | `2027-07-15T00:00:00Z` + 1d | Geometric | Both score 64.0; both longest=8h | Request input order preserved (Alpha #1, Beta #2). Equivalence stated | **PASSED** |
| **REF-08** | Terrain Rejection | Apollo 11 (0.67408°, 23.47297°) | `2027-07-15T12:00:00Z` | Terrain | Outside Product 90 (80°S-90°S) | `422 TERRAIN_UNAVAILABLE`. Zero fallback to geometric mode | **PASSED** |

---

## 3. Numerical UI Agreement Audit (Task 2)

| Parameter | API Field / Contract Requirement | Redesigned UI Presentation | Audit Result |
| :--- | :--- | :--- | :--- |
| **Site Identification** | `site.name`, `latitude`, normalized `longitude` | Displays resolved site name, latitude°, and normalized longitude in $[-180, 180)^\circ$ | **AGREED** |
| **Observation Timestamp** | ISO 8601 UTC ending in Z | Displayed as `<time dateTime="...">... (UTC)</time>` | **AGREED** |
| **Sun / Earth Angles** | `point[body].azimuth_deg`, `elevation_deg` | Formatted directly from returned numbers in degrees without decorative modification | **AGREED** |
| **Horizon Thresholds** | `point[body].horizon_elevation_deg` | Explicitly shown in table column; 0.0° in geometric, physical DEM threshold in terrain | **AGREED** |
| **Visibility Flags** | `point[body].visible` (boolean) | Rendered as "Yes"/"No" or "Visible"/"Not visible" based strictly on boolean flag | **AGREED** |
| **Simultaneous Availability**| `point.is_golden_window` (boolean) | "Simultaneous availability: Yes/No" or "Simultaneous golden state: Yes/No" | **AGREED** |
| **Timeline Metrics** | `summary.sunlit_hours`, `_pct`, `longest_golden_window_hours` | Rendered with exact hours and percentages from API summary object | **AGREED** |
| **Scenario Ranking** | `ranked_scenarios` array order & `rank` | Table renders in exact returned order; uses backend `rank` integer ($1..N$) | **AGREED** |
| **Ranking Score** | `score = 0.40*S + 0.30*E + 0.30*G` | Displays returned backend score; disclaimer clarifies product score vs NASA cert | **AGREED** |

No mocked or decorative metrics (e.g. power generation in watts, antenna communication bandwidth in Mbps) are present.

---

## 4. 3D Scene Agreement & Coordinate Transformations (Task 3)

### 4.1 Global Moon Scene
- **Frame**: Moon-Centered Moon-Fixed (MCMF) Cartesian unit sphere ($R=2.5$ display units).
- **Mapping to Three.js**:
  $$\text{scene.x} = +\vec{v}_{\text{mcmf}, x}, \quad \text{scene.y} = +\vec{v}_{\text{mcmf}, z} \text{ (North Pole at }+Y\text{)}, \quad \text{scene.z} = -\vec{v}_{\text{mcmf}, y} \text{ (90°E at }-Z\text{)}$$
- **Sun & Earth Vectors**: Computed from topocentric ENU unit vectors rotated via $\text{enuToMoonFixed}$ at observer latitude and normalized longitude. Never synthesized.
- **Far-side Markers**: Identified via surface normal depth check $\hat{n} \cdot \vec{v}_{\text{cam}} < 0$; rendered with translucent opacity (0.35) without coordinate displacement.

### 4.2 Communication Link Verification
- **Link Line**: Segment from Earth representation position to lunar site surface position.
- **Visible Condition (`earth.visible === true`)**: Continuous glowing cyan beam (`#00f0ff`, opacity 0.85) with traveling signal pulse towards Moon. HUD status: `Earth Link: Active (Line of sight open)`.
- **Blocked Condition (`earth.visible === false`)**: Dashed gray line (`#666666`, opacity 0.45) with pulse disabled. HUD status: `Earth Link: Blocked (No line of sight)`.
- **Unknown Condition (`observationPoint === null` or `isLoading`)**: Line omitted entirely. HUD status: `Link: Awaiting ephemeris…`. Unknown data never displays an active link.

### 4.3 Local Terrain Inspector
- **Frame**: Topocentric ENU ($\text{scene.x} = +\text{east}$, $\text{scene.y} = +\text{up}$, $\text{scene.z} = -\text{north}$).
- **Mesh Orientation**: Rows increase north, columns increase east, array indexing $r \times \text{width} + c$. 1:1 scale preservation.
- **Elevation Sign**: Surface elevation positive above local reference radius; observer height ($+2.0\text{ m}$) offset added upwards along $+Y$.

---

## 5. Regression Test Results (Task 4)

The results below are recorded from the acceptance run dated 2026-11-15. They are historical evidence and are not a claim that those commands were rerun during later integrations.

- **Backend Test Suite**:
  - Command: `python -m pytest`
  - Result: **403 passed**, 16 skipped (live Horizons probes and live PostgreSQL requiring external network/DB), 0 failed.
- **Backend Linting**:
  - Command: `ruff check app tests`
  - Result: **All checks passed** (0 errors).
- **Frontend Test Suite**:
  - Command: `vitest run`
  - Result: **199 passed** across 16 test files, 0 failed.
- **Frontend Typecheck & Production Build**:
  - Command: `tsc -b && vite build`
  - Result: **Built successfully** in 6.85s without TypeScript errors.

---

## 6. Model & Operational Limitations

1. **JPL Horizons Ephemeris Concurrency**: Bounded live ephemeris retrieval uses sequential provider concurrency locks to respect Horizons rate limits.
2. **Terrain Footprint**: Numerical terrain coverage is currently registered for LOLA Product 90 (80°S–90°S). Regions outside this footprint reject terrain mode with `422 TERRAIN_UNAVAILABLE`.
3. **Product Score vs Certification**: The v1 score is a deterministic comparative metric for scenario evaluation, not a flight safety certification.

---

## 7. Acceptance Sign-off

- [x] Reference scenarios frozen with exact inputs and outputs.
- [x] Numerical UI values strictly match authoritative backend results.
- [x] Global and local 3D scene coordinate frames verified mathematically.
- [x] Communication link governed strictly by authoritative Earth visibility.
- [x] Full regression test suites passed with zero failures.

**Recommendation:** The redesigned presentation preserves complete scientific correctness and is accepted for release consideration.
