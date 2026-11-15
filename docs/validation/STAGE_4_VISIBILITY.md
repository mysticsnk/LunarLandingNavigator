# Stage 4 Terrain-Aware Astronomy & Visibility Validation Report

This document records the design, implementation, and scientific verification of the
Stage 4 terrain-aware astronomical visibility service for the Lunar Landing Site Navigator.

## 1. Scope & System Roles

- **Assigned Area:** Integration of numerical terrain and curved-surface local horizon
  calculations with ephemerides, single-instant observations, multi-day timelines, and
  continuous visibility windows.
- **Physical Integration Roles:**
  - **Bohdan (Terrain Modeling):** Provides numerical terrain sampling (`TerrainGrid`,
    `TerrainSource`) and curved-Moon horizon evaluation (`TerrainHorizonService`,
    `ObserverSurface`, `HorizonResult`, `TerrainCoverageError`).
  - **Astronomy Service (This Area):** Resolves observer position and surface elevation,
    queries JPL Horizons at the physical observer altitude above the reference sphere,
    evaluates terrain horizon thresholds along each body's respective azimuth, calculates
    terrain-aware visibility flags, and detects modified continuous windows.
  - **Yaroslav (Storage & Worker):** Consumes `calculate_observation` and `calculate_timeline`
    or `calculate_terrain_observation` and `calculate_terrain_timeline` when dispatching jobs.
  - **Sasha & Slavik (UI & 3D Scene):** Receive terrain-aware `horizon_elevation_deg`,
    `surface_elevation_m`, `terrain_dataset_id`, and uncompromised astronomical `direction_enu`
    vectors for scene playback and numerical display.

## 2. Observer Elevation & Physical Conventions

### 2.1 Observer Resolution
1. For terrain mode, the observer's source surface elevation ($z_{\text{surf}}$) is resolved
   from the terrain service (`TerrainHorizonService.observer_surface.surface_elevation_m`).
2. The user-requested instrument height ($h_{\text{obs}}$ in $[0, 20]\text{ m}$) is added to
   establish the physical observer altitude above the lunar reference sphere ($R = 1,737,400\text{ m}$):
   $$z_{\text{total}} = z_{\text{surf}} + h_{\text{obs}}$$
3. The exact physical altitude ($z_{\text{total}}$ in km) is passed to the JPL Horizons provider
   (`SITE_COORD="{lon},{lat},{z_total/1000.0}"`). This ensures topocentric apparent angles and
   terrain horizon angles are calculated for the exact same observer location in space.
4. In geometric mode, $z_{\text{surf}} = 0.0$ is maintained, querying Horizons at $h_{\text{obs}}$.

### 2.2 Direction Vector & Sky Position Invariance
- Celestial body direction vectors ($\text{direction\_enu}$) remain the exact astronomical unit
  direction vectors from the observer to the celestial body center in local East-North-Up coordinates:
  $$\text{east} = \cos(\text{elevation}) \cdot \sin(\text{azimuth})$$
  $$\text{north} = \cos(\text{elevation}) \cdot \cos(\text{azimuth})$$
  $$\text{up} = \sin(\text{elevation})$$
- Vector invariance: $\text{east}^2 + \text{north}^2 + \text{up}^2 = 1.0 \pm 10^{-6}$.
- Physical obstruction by terrain does **not** displace or distort the body's position in the sky.

### 2.3 Independent Azimuth Horizons & Visibility Thresholds
- The Sun and Earth generally occupy different azimuths in the lunar sky.
- The terrain horizon is evaluated along each body's own azimuth:
  $$\theta_{\text{horizon, sun}} = \text{terrain\_service.horizon\_elevation}(\text{azimuth}_{\text{sun}})$$
  $$\theta_{\text{horizon, earth}} = \text{terrain\_service.horizon\_elevation}(\text{azimuth}_{\text{earth}})$$
- Strict visibility inequality applying the visibility margin:
  $$\text{visible}_{\text{body}} = \theta_{\text{body}} > \theta_{\text{horizon, body}} + \text{margin}$$
- Golden window: $\text{is\_golden\_window} = \text{visible}_{\text{sun}} \land \text{visible}_{\text{earth}}$.

## 3. Geometric vs. Terrain Mode Differences

| Attribute | Geometric Mode | Terrain Mode |
|---|---|---|
| Surface Elevation | $0.0\text{ m}$ (nominal reference sphere) | Resolved from DEM/DTM ($z_{\text{surf}}$) |
| Observer Altitude in Horizons | $h_{\text{obs}}$ | $z_{\text{surf}} + h_{\text{obs}}$ |
| Horizon Elevation Threshold | Constant $0.0^\circ$ (tangent plane) | Dynamic $\theta_{\text{horizon}}(\text{azimuth})$ |
| Crater / Ridge Obstruction | Ignored; positive elevation is always visible | Blocked when $\theta_{\text{body}} \le \theta_{\text{horizon}}$ |
| Elevated Summit / Peak Horizon | Constant $0.0^\circ$ | Dips below $0.0^\circ$ (e.g. $-2^\circ$ to $-3.5^\circ$) |
| Negative Elevation Visibility | Never visible ($\le 0.0^\circ$) | Visible if body is above dipping horizon |
| Dataset Provenance | `terrain_dataset_id = None` | `terrain_dataset_id = "{dataset_id}"` |

### Non-Intuitive Visibility on Elevated Peaks
Terrain mode does **not** strictly reduce visibility. An observer situated on a high mountain summit
or crater rim peak looking downward over lower surrounding plains experiences a negative horizon
due to lunar curvature:
$$\theta_{\text{horizon}} \approx -\arccos\left(\frac{R + z_{\text{surrounding}}}{R + z_{\text{observer}}}\right)$$
For a $3,000\text{ m}$ summit overlooking lower terrain, the horizon dips to approximately $-3.3^\circ$.
A celestial body at $-0.5^\circ$ elevation is invisible in geometric mode ($\le 0.0^\circ$), but
is physically visible above the horizon in terrain mode.

## 4. Timeline & Continuous Window Integration

Every timeline sample $t_i \in [start\_time, end\_time)$ evaluates terrain horizon elevation at that
sample's instantaneous Sun and Earth azimuths. The existing interval detection and summary logic
operate on the resulting terrain visibility booleans:
- **Window Shortening:** A terrain ridge on the western horizon blocks low-elevation setting Sun,
  causing sunset to occur earlier than geometric sunset.
- **Window Splitting:** A narrow intervening ridge or peak blocks the body during intermediate hours,
  splitting what was a continuous 24-hour geometric window into two distinct intervals.
- **Window Removal:** High crater walls surrounding a shadowed crater floor prevent sunlight from
  reaching the floor, completely removing the sunlight window ($\text{sunlit\_hours} = 0.0$).
- **No Fallback:** If terrain data is unavailable (`outside_coverage` or `no_data`), the service
  raises structured `TerrainCoverageError`. Missing terrain is never replaced with zero elevation
  or converted into geometric mode.

## 5. Verification Suite Summary

Tests implemented in `backend/tests/test_terrain_visibility.py`:

| Test Name | Verified Behavior | Status |
|---|---|---|
| `test_terrain_mode_resolves_surface_and_passes_correct_altitude_to_horizons` | $z_{\text{surf}} + h_{\text{obs}}$ passed to Horizons `SITE_COORD` | PASSED |
| `test_object_above_zero_but_below_ridge_is_blocked` | Sun at $+2.0^\circ$ blocked by $+3.4^\circ$ ridge | PASSED |
| `test_direction_vectors_remain_astronomical_direction_when_blocked` | Direction ENU vector unchanged and normalized when blocked | PASSED |
| `test_sun_and_earth_have_independent_horizon_thresholds` | Sun faces ridge ($+3.5^\circ$), Earth faces plain ($-0.08^\circ$) | PASSED |
| `test_visibility_margin_changes_threshold_correctly` | Margin $1.0^\circ$ shifts visibility cutoff strictly | PASSED |
| `test_higher_observer_unblocks_visibility` | Raising observer from $2\text{m}$ to $20\text{m}$ restores visibility | PASSED |
| `test_missing_terrain_produces_structured_failure` | `outside_coverage` and `no_data` raise `TerrainCoverageError` | PASSED |
| `test_negative_horizon_mode_difference` | $3,000\text{m}$ peak has horizon $<-2.0^\circ$; Sun at $-0.5^\circ$ is visible | PASSED |
| `test_terrain_timeline_modifies_windows` | Terrain removes or splits timeline continuous windows | PASSED |
| `test_unified_observation_and_timeline_entrypoints` | Unified functions dispatch mode or reject missing terrain service | PASSED |

## 6. Limitations

1. **Raster Resolution Limit:** Topographic features smaller than the underlying numerical grid
   resolution (e.g. $20\text{ m}$ regional LDEM or $5\text{ m}$ local DTM) cannot be resolved.
2. **Radial Step Discretization:** Horizon rays are sampled at discrete intervals (typically half
   the grid resolution). Sub-step sharp boulders or pinnacles may escape detection.
3. **Temporal Sampling Discretization:** Timeline evaluations use discrete steps (`step_minutes`).
   Short occultations lasting less than the step size are not captured.
4. **Point-Source Body Center:** Calculations evaluate center-of-body geometric rays without
   finite solar disc partial penumbra or diffraction.
