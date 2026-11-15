import * as THREE from 'three'
import { latLonToGlobalScene, type LunarCoordinate } from '../../lib/coordinates'

export function buildMoonGraticuleGeometry(radius: number): THREE.BufferGeometry {
  const positions: number[] = []
  const addLine = (coordinates: LunarCoordinate[]) => {
    const points = coordinates.map((coordinate) => latLonToGlobalScene(coordinate, radius))
    for (let index = 0; index < points.length - 1; index++) {
      positions.push(
        points[index].x, points[index].y, points[index].z,
        points[index + 1].x, points[index + 1].y, points[index + 1].z,
      )
    }
  }

  for (let latitude = -60; latitude <= 60; latitude += 30) {
    addLine(Array.from({ length: 181 }, (_, index) => ({ latitude, longitude: -180 + index * 2 })))
  }
  for (let longitude = -180; longitude < 180; longitude += 30) {
    addLine(Array.from({ length: 91 }, (_, index) => ({ latitude: -90 + index * 2, longitude })))
  }

  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3))
  return geometry
}
