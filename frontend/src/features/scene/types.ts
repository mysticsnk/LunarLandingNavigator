/**
 * Types for 3D Lunar Local Scene Visualization (Stage 4)
 */

import type { EnuVector } from '../../lib/coordinates'
import type { Heightmap, NowResult, ResolvedSite, Site } from '../../api/types'

export type ObservationPoint = NowResult['point']
export type { Heightmap }

export interface LunarSceneProps {
  className?: string
  /**
   * Topocentric ENU unit direction vector towards the Sun.
   * Null when not yet calculated or unavailable.
   */
  sunDirectionEnu?: EnuVector | null
  /**
   * Topocentric ENU unit direction vector towards Earth.
   * Null when not yet calculated or unavailable.
   */
  earthDirectionEnu?: EnuVector | null
  /**
   * Direct observation point matching canonical API contract.
   * If provided, timestamp and azimuth/elevation angles are extracted directly.
   */
  observationPoint?: ObservationPoint | null
  /**
   * Resolved or catalog site.
   */
  site?: ResolvedSite | Site | null
  /**
   * Height of the observer above the model surface in metres.
   * Default: 2.0 metres.
   */
  observerHeightM?: number
  horizonMode?: 'geometric' | 'terrain'
  terrainDatasetId?: string | null
  visibilityMarginDeg?: number
  /**
   * Whether ephemeris or terrain data is currently loading.
   */
  isLoading?: boolean
  /**
   * Data status from result metadata ('fresh' | 'cached').
   */
  dataStatus?: 'fresh' | 'cached' | null
  /**
   * Explicit requested observation timestamp (preserved across cached requests).
   */
  timestamp?: string | null
  /**
   * Numerical terrain heightmap for local elevation mesh in Stage 4.
   */
  heightmap?: Heightmap | null
  /**
   * Whether numerical terrain heightmap is loading.
   */
  isTerrainLoading?: boolean
  /**
   * Human-readable error if terrain heightmap failed to load.
   */
  terrainError?: string | null
  /**
   * Visual vertical exaggeration for local terrain mesh.
   * Defaults strictly to 1.0 (physical 1:1 scale).
   * Visual exaggeration never alters backend visibility flags.
   */
  visualExaggeration?: number
  /**
   * Multiplier used strictly for rendering distance/marker visibility.
   * Kept strictly separated from physical coordinates.
   * Default: 1.0.
   */
  visualScale?: number
  /**
   * Optional flag indicating that demonstration vectors are active.
   * When true, an explicit demonstration badge is shown.
   */
  demonstrationMode?: boolean
  /**
   * Optional callback triggered if a WebGL rendering error occurs.
   */
  onError?: (error: Error) => void
}

/**
 * Props for the 3D Global Moon Viewport (Stage 5)
 */
export interface GlobalMoonSceneProps {
  className?: string
  /**
   * Catalog landing sites to display as markers on the global Moon.
   */
  catalogSites?: Site[] | null
  /**
   * Currently selected landing site (catalog or resolved).
   */
  selectedSite?: ResolvedSite | Site | null
  /**
   * Currently selected lunar coordinate.
   */
  selectedCoordinate?: { latitude: number; longitude: number } | null
  /**
   * Callback when a coordinate on the Moon or a site is selected.
   */
  onSelectCoordinate?: (coord: { latitude: number; longitude: number }) => void
  /**
   * Callback when a catalog site is clicked.
   */
  onSelectSite?: (site: Site) => void
  /**
   * Direct observation point matching canonical API contract.
   * Drives global Sun/Earth direction vectors and communication link visibility.
   */
  observationPoint?: ObservationPoint | null
  /**
   * Loading state flag.
   */
  isLoading?: boolean
  /**
   * Data freshness status from result metadata ('fresh' | 'cached').
   */
  dataStatus?: 'fresh' | 'cached' | null
  /**
   * Optional flag indicating demonstration vectors.
   */
  demonstrationMode?: boolean
  /**
   * Optional callback triggered if a WebGL rendering error occurs.
   */
  onError?: (error: Error) => void
}
