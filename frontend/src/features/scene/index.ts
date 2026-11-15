export { LunarScene } from './LunarScene'
export { GlobalMoonScene } from './GlobalMoonScene'
export { SceneErrorBoundary } from './SceneErrorBoundary'
export { useHeightmap, clearHeightmapCache } from './useHeightmap'
export {
  buildTerrainGeometry,
  validateHeightmap,
  getLocalSurfaceElevationAtOrigin,
} from './terrainMesh'
export type {
  LunarSceneProps,
  GlobalMoonSceneProps,
  ObservationPoint,
  Heightmap,
} from './types'
