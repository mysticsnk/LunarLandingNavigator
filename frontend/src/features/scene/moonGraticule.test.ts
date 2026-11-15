import { describe, expect, it } from 'vitest'
import { buildMoonGraticuleGeometry } from './moonGraticule'

describe('moon graticule geometry', () => {
  it('builds latitude and longitude lines just above the textured sphere', () => {
    const geometry = buildMoonGraticuleGeometry(2.505)
    const positions = geometry.getAttribute('position')

    expect(positions.count).toBe(3960)
    for (let index = 0; index < positions.count; index++) {
      expect(Math.hypot(positions.getX(index), positions.getY(index), positions.getZ(index))).toBeCloseTo(2.505, 3)
    }
  })
})
