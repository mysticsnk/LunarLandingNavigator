import { describe, expect, it } from 'vitest'
import { heightmapFixture } from '../../test/fixtures'
import {
  buildTerrainGeometry,
  getLocalSurfaceElevationAtOrigin,
  getTerrainCameraFrame,
  validateHeightmap,
} from './terrainMesh'

describe('terrainMesh geometry & validation', () => {
  describe('validateHeightmap', () => {
    it('accepts a fully valid canonical Heightmap payload', () => {
      const validated = validateHeightmap(heightmapFixture)
      expect(validated.region_id).toBe('shackleton_connecting_ridge')
      expect(validated.frame).toBe('local_enu')
      expect(validated.width).toBe(5)
      expect(validated.height).toBe(5)
    })

    it('rejects payloads with wrong frame (e.g. not local_enu)', () => {
      expect(() =>
        validateHeightmap({ ...heightmapFixture, frame: 'moon_me' }),
      ).toThrow(/Invalid heightmap frame/)
    })

    it('rejects payloads with invalid or non-positive dimensions', () => {
      expect(() =>
        validateHeightmap({ ...heightmapFixture, width: 0 }),
      ).toThrow(/width must be a positive integer/)
      expect(() =>
        validateHeightmap({ ...heightmapFixture, height: -1 }),
      ).toThrow(/height must be a positive integer/)
    })

    it('rejects non-positive spacing_m', () => {
      expect(() =>
        validateHeightmap({ ...heightmapFixture, spacing_m: 0 }),
      ).toThrow(/spacing_m must be a positive finite number/)
      expect(() =>
        validateHeightmap({ ...heightmapFixture, spacing_m: -10 }),
      ).toThrow(/spacing_m must be a positive finite number/)
    })

    it('rejects elevation array length mismatch', () => {
      expect(() =>
        validateHeightmap({
          ...heightmapFixture,
          elevation_m: [1, 2, 3], // width 5 * height 5 = 25 required
        }),
      ).toThrow(/Invalid heightmap elevation_m length/)
    })

    it('rejects non-finite elevations (NaN, Infinity)', () => {
      const withNan = [...heightmapFixture.elevation_m]
      withNan[2] = Number.NaN
      expect(() =>
        validateHeightmap({ ...heightmapFixture, elevation_m: withNan }),
      ).toThrow(/non-finite value/)

      const withInf = [...heightmapFixture.elevation_m]
      withInf[4] = Number.POSITIVE_INFINITY
      expect(() =>
        validateHeightmap({ ...heightmapFixture, elevation_m: withInf }),
      ).toThrow(/non-finite value/)
    })

    it('rejects invalid or missing origin coordinates', () => {
      expect(() =>
        validateHeightmap({ ...heightmapFixture, origin: null }),
      ).toThrow(/valid origin/)
      expect(() =>
        validateHeightmap({
          ...heightmapFixture,
          origin: { latitude: Number.NaN, longitude: 0, elevation_m: 0 },
        }),
      ).toThrow(/valid origin/)
    })

    it('rejects missing metadata strings', () => {
      expect(() =>
        validateHeightmap({ ...heightmapFixture, region_id: '' }),
      ).toThrow(/region_id is required/)
      expect(() =>
        validateHeightmap({ ...heightmapFixture, dataset_id: undefined }),
      ).toThrow(/dataset_id is required/)
    })
  })

  describe('buildTerrainGeometry', () => {
    it('applies agreed scene orientation (scene.x = east, scene.y = up, scene.z = -north)', () => {
      // 2x2 grid for exact point inspection
      const simpleHeightmap = {
        ...heightmapFixture,
        width: 2,
        height: 2,
        east_min_m: -10,
        north_min_m: -20,
        spacing_m: 10,
        elevation_m: [
          100, 110, // row 0: north = -20; col 0: east = -10; col 1: east = 0
          120, 130, // row 1: north = -10; col 0: east = -10; col 1: east = 0
        ],
      }

      const geo = buildTerrainGeometry(simpleHeightmap)
      const positions = geo.getAttribute('position')

      // Total 4 vertices
      expect(positions.count).toBe(4)

      // Vertex 0 (r=0, c=0): east = -10, north = -20, up = 100
      // scene.x = -10, scene.y = 100, scene.z = -(-20) = 20
      expect(positions.getX(0)).toBe(-10)
      expect(positions.getY(0)).toBe(100)
      expect(positions.getZ(0)).toBe(20)

      // Vertex 1 (r=0, c=1): east = 0, north = -20, up = 110
      // scene.x = 0, scene.y = 110, scene.z = 20
      expect(positions.getX(1)).toBe(0)
      expect(positions.getY(1)).toBe(110)
      expect(positions.getZ(1)).toBe(20)

      // Vertex 2 (r=1, c=0): east = -10, north = -10, up = 120
      // scene.x = -10, scene.y = 120, scene.z = 10
      expect(positions.getX(2)).toBe(-10)
      expect(positions.getY(2)).toBe(120)
      expect(positions.getZ(2)).toBe(10)

      // Vertex 3 (r=1, c=1): east = 0, north = -10, up = 130
      // scene.x = 0, scene.y = 130, scene.z = 10
      expect(positions.getX(3)).toBe(0)
      expect(positions.getY(3)).toBe(130)
      expect(positions.getZ(3)).toBe(10)

      // Index count: 1 quad * 2 triangles * 3 vertices = 6 indices
      const index = geo.getIndex()
      expect(index).not.toBeNull()
      expect(index!.count).toBe(6)
      expect(geo.getAttribute('normal').getY(0)).toBeGreaterThan(0)
    })

    it('preserves horizontal and vertical scale consistency with uniform scaling', () => {
      const uniformScale = 0.5
      const geo = buildTerrainGeometry(heightmapFixture, { scale: uniformScale })
      const positions = geo.getAttribute('position')

      // Check first vertex (r=0, c=0): east_min = -100, north_min = -100, elev = 0
      expect(positions.getX(0)).toBe(-100 * uniformScale)
      expect(positions.getY(0)).toBe(0)
      expect(positions.getZ(0)).toBe(100 * uniformScale)
    })

    it('applies visual exaggeration strictly to vertical elevation without shifting horizontal coordinates', () => {
      const exaggeration = 2.0
      const geo = buildTerrainGeometry(heightmapFixture, { exaggeration })
      const positions = geo.getAttribute('position')

      // Center vertex (r=2, c=2): east = 0, north = 0, elev = 12
      // index = 2 * 5 + 2 = 12
      expect(positions.getX(12)).toBe(0)
      expect(positions.getY(12)).toBe(12 * exaggeration) // 24
      expect(positions.getZ(12)).toBe(-0)
    })

    it('centers and frames the full terrain bounds for the viewport aspect ratio', () => {
      const geometry = buildTerrainGeometry(heightmapFixture, { scale: 0.05, exaggeration: 5 })
      const frame = getTerrainCameraFrame(geometry, 45, 16 / 9)

      expect(frame.center.x).toBeCloseTo(0)
      expect(frame.center.y).toBeCloseTo(1.5)
      expect(frame.center.z).toBeCloseTo(0)
      expect(frame.distance).toBeGreaterThan(frame.center.length())
      expect(Number.isFinite(frame.distance)).toBe(true)
    })
  })

  describe('getLocalSurfaceElevationAtOrigin', () => {
    it('correctly calculates surface elevation at local origin (0, 0)', () => {
      // heightmapFixture has center at r=2, c=2 (east_min=-100 + 2*50 = 0, north_min=-100 + 2*50 = 0)
      // elevation at index 12 is 12.0
      const elev = getLocalSurfaceElevationAtOrigin(heightmapFixture)
      expect(elev).toBeCloseTo(12.0, 4)
    })
  })
})
