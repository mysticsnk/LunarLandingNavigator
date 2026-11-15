import * as THREE from 'three'
import type { Heightmap } from '../../api/types'

export interface TerrainMeshOptions {
  /**
   * Visual exaggeration multiplier for vertical scale (elevation).
   * Defaults strictly to 1.0 (physical 1:1 scale).
   * Must never alter underlying astronomical or visibility calculations.
   */
  exaggeration?: number
  /**
   * Uniform visual scaling factor applied equally to all axes (X, Y, Z)
   * to preserve horizontal/vertical scale consistency in the local viewport.
   * Defaults to 1.0 (1 metre = 1 scene unit).
   */
  scale?: number
}

/**
 * Validates a numerical heightmap against canonical API contract invariants:
 * - frame === 'local_enu'
 * - positive integer dimensions (width, height)
 * - positive spacing_m
 * - elevation_m array length === width * height
 * - all elevations finite numbers
 * - valid origin coordinates
 */
export function validateHeightmap(data: unknown): Heightmap {
  if (
    !data ||
    typeof data !== 'object' ||
    Array.isArray(data)
  ) {
    throw new Error('Invalid heightmap: payload must be a non-null object')
  }

  const h = data as Record<string, unknown>

  if (typeof h.region_id !== 'string' || !h.region_id) {
    throw new Error('Invalid heightmap: region_id is required')
  }
  if (typeof h.dataset_id !== 'string') {
    throw new Error('Invalid heightmap: dataset_id is required')
  }
  if (typeof h.model_version !== 'string') {
    throw new Error('Invalid heightmap: model_version is required')
  }
  if (h.frame !== 'local_enu') {
    throw new Error(`Invalid heightmap frame: expected 'local_enu', got '${h.frame}'`)
  }

  const origin = h.origin as Record<string, unknown> | null | undefined
  if (
    !origin ||
    typeof origin !== 'object' ||
    typeof origin.latitude !== 'number' ||
    !Number.isFinite(origin.latitude) ||
    typeof origin.longitude !== 'number' ||
    !Number.isFinite(origin.longitude) ||
    typeof origin.elevation_m !== 'number' ||
    !Number.isFinite(origin.elevation_m)
  ) {
    throw new Error('Invalid heightmap: valid origin {latitude, longitude, elevation_m} is required')
  }

  if (typeof h.east_min_m !== 'number' || !Number.isFinite(h.east_min_m)) {
    throw new Error('Invalid heightmap: east_min_m must be a finite number')
  }
  if (typeof h.north_min_m !== 'number' || !Number.isFinite(h.north_min_m)) {
    throw new Error('Invalid heightmap: north_min_m must be a finite number')
  }
  if (typeof h.spacing_m !== 'number' || !Number.isFinite(h.spacing_m) || h.spacing_m <= 0) {
    throw new Error('Invalid heightmap: spacing_m must be a positive finite number')
  }
  if (typeof h.width !== 'number' || !Number.isInteger(h.width) || h.width < 1) {
    throw new Error('Invalid heightmap: width must be a positive integer')
  }
  if (typeof h.height !== 'number' || !Number.isInteger(h.height) || h.height < 1) {
    throw new Error('Invalid heightmap: height must be a positive integer')
  }

  if (!Array.isArray(h.elevation_m)) {
    throw new Error('Invalid heightmap: elevation_m must be an array')
  }
  if (h.elevation_m.length !== h.width * h.height) {
    throw new Error(
      `Invalid heightmap elevation_m length: expected ${h.width * h.height} (width=${h.width} * height=${h.height}), got ${h.elevation_m.length}`,
    )
  }

  for (let i = 0; i < h.elevation_m.length; i++) {
    const val = h.elevation_m[i]
    if (typeof val !== 'number' || !Number.isFinite(val)) {
      throw new Error(`Invalid heightmap elevation_m at index ${i}: non-finite value encountered`)
    }
  }

  if (typeof h.source_url !== 'string') {
    throw new Error('Invalid heightmap: source_url is required')
  }
  if (typeof h.attribution !== 'string') {
    throw new Error('Invalid heightmap: attribution is required')
  }

  return h as unknown as Heightmap
}

/**
 * Builds a Three.js BufferGeometry for the local terrain mesh from a validated Heightmap.
 *
 * Conventions:
 * - Rows increase north (row r in [0, height-1])
 * - Columns increase east (column c in [0, width-1])
 * - Array index: index = row * width + column
 * - Local ENU coordinates:
 *     east = east_min_m + c * spacing_m
 *     north = north_min_m + r * spacing_m
 *     up = elevation_m[index] * exaggeration
 * - Scene coordinates (Three.js):
 *     scene.x = +east * scale
 *     scene.y = +up * scale
 *     scene.z = -north * scale
 *
 * Horizontal and vertical scale consistency is preserved: scale is uniform across X, Y, Z.
 */
export function buildTerrainGeometry(
  heightmap: Heightmap,
  options?: TerrainMeshOptions,
): THREE.BufferGeometry {
  const { width, height, spacing_m, east_min_m, north_min_m, elevation_m } = heightmap
  const exaggeration = options?.exaggeration ?? 1.0
  const scale = options?.scale ?? 1.0

  const vertexCount = width * height
  const positions = new Float32Array(vertexCount * 3)

  for (let r = 0; r < height; r++) {
    const north = north_min_m + r * spacing_m
    const z = -north * scale

    for (let c = 0; c < width; c++) {
      const east = east_min_m + c * spacing_m
      const x = east * scale
      const index = r * width + c
      const up = elevation_m[index] * exaggeration
      const y = up * scale

      const vIdx = index * 3
      positions[vIdx] = x
      positions[vIdx + 1] = y
      positions[vIdx + 2] = z
    }
  }

  const quadsX = width - 1
  const quadsY = height - 1
  const indexCount = quadsX * quadsY * 6
  const indices = new Uint32Array(indexCount)

  let idx = 0
  for (let r = 0; r < quadsY; r++) {
    for (let c = 0; c < quadsX; c++) {
      const i00 = r * width + c
      const i01 = r * width + (c + 1)
      const i10 = (r + 1) * width + c
      const i11 = (r + 1) * width + (c + 1)

      // Triangle 1: i00, i10, i01 (facing +Y upwards)
      indices[idx++] = i00
      indices[idx++] = i10
      indices[idx++] = i01

      // Triangle 2: i01, i10, i11 (facing +Y upwards)
      indices[idx++] = i01
      indices[idx++] = i10
      indices[idx++] = i11
    }
  }

  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
  geometry.setIndex(new THREE.BufferAttribute(indices, 1))
  geometry.computeVertexNormals()

  return geometry
}

/**
 * Bilinearly samples local surface elevation at (east=0, north=0) in local ENU,
 * which corresponds to the site location / origin.
 */
export function getLocalSurfaceElevationAtOrigin(heightmap: Heightmap): number {
  const { width, height, spacing_m, east_min_m, north_min_m, elevation_m } = heightmap

  // Origin is at east = 0, north = 0
  const colF = (0 - east_min_m) / spacing_m
  const rowF = (0 - north_min_m) / spacing_m

  // If outside bounds, clamp to closest cell or return origin elevation
  if (colF < 0 || colF > width - 1 || rowF < 0 || rowF > height - 1) {
    return 0.0
  }

  const c0 = Math.floor(colF)
  const c1 = Math.min(width - 1, c0 + 1)
  const r0 = Math.floor(rowF)
  const r1 = Math.min(height - 1, r0 + 1)

  const dfC = colF - c0
  const dfR = rowF - r0

  const e00 = elevation_m[r0 * width + c0]
  const e01 = elevation_m[r0 * width + c1]
  const e10 = elevation_m[r1 * width + c0]
  const e11 = elevation_m[r1 * width + c1]

  const top = e00 * (1 - dfC) + e01 * dfC
  const bottom = e10 * (1 - dfC) + e11 * dfC

  return top * (1 - dfR) + bottom * dfR
}
