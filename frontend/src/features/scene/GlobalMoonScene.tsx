import React, { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import {
  enuToMoonFixed,
  latLonToGlobalScene,
  moonFixedToGlobalScene,
  normalizeLongitude,
  type LunarCoordinate,
} from '../../lib/coordinates'
import { SceneErrorBoundary } from './SceneErrorBoundary'
import type { GlobalMoonSceneProps } from './types'
import type { Site, ResolvedSite } from '../../api/types'

/** Physical and display constants */
const MOON_RADIUS = 2.5
const SUN_DISTANCE = 11.0
const EARTH_DISTANCE = 8.5
const DEFAULT_CAMERA_POS: [number, number, number] = [3.5, 2.2, 6.0]
const SOUTH_POLE_CAMERA_POS: [number, number, number] = [0.1, -6.5, 2.0]
const NEAR_SIDE_CAMERA_POS: [number, number, number] = [7.0, 0.5, 0.0]
const FAR_SIDE_CAMERA_POS: [number, number, number] = [-7.0, 0.5, 0.0]

/**
 * Creates an offline, zero-network procedural lunar surface texture.
 * Ensures the scene never fails due to missing external image assets.
 */
function createProceduralMoonTexture(): THREE.CanvasTexture {
  const canvas = document.createElement('canvas')
  canvas.width = 1024
  canvas.height = 512
  const ctx = canvas.getContext('2d')

  if (ctx) {
    // Base lunar highland anorthosite gray
    ctx.fillStyle = '#8f9299'
    ctx.fillRect(0, 0, 1024, 512)

    // Darker basaltic maria basins (Oceanus Procellarum, Mare Imbrium, Mare Tranquillitatis)
    const maria = [
      { x: 380, y: 190, r: 120, opacity: 0.45 }, // Oceanus Procellarum
      { x: 470, y: 170, r: 85, opacity: 0.5 },  // Mare Imbrium
      { x: 500, y: 220, r: 70, opacity: 0.4 },  // Mare Serenitatis
      { x: 570, y: 240, r: 65, opacity: 0.45 }, // Mare Tranquillitatis
      { x: 620, y: 230, r: 50, opacity: 0.35 }, // Mare Crisium
      { x: 440, y: 310, r: 55, opacity: 0.35 }, // Mare Nubium
    ]

    for (const m of maria) {
      const grad = ctx.createRadialGradient(m.x, m.y, 10, m.x, m.y, m.r)
      grad.addColorStop(0, `rgba(45, 48, 56, ${m.opacity})`)
      grad.addColorStop(0.7, `rgba(60, 64, 72, ${m.opacity * 0.7})`)
      grad.addColorStop(1, 'rgba(143, 146, 153, 0)')
      ctx.fillStyle = grad
      ctx.beginPath()
      ctx.arc(m.x, m.y, m.r, 0, Math.PI * 2)
      ctx.fill()
    }

    // Prominent rayed impact craters (Tycho, Copernicus, Kepler)
    const craters = [
      { x: 480, y: 360, r: 14, rays: 12, rayLen: 120 }, // Tycho
      { x: 440, y: 210, r: 12, rays: 8, rayLen: 70 },   // Copernicus
      { x: 410, y: 220, r: 8, rays: 6, rayLen: 45 },    // Kepler
    ]

    for (const c of craters) {
      // Crater rim and bright floor
      ctx.fillStyle = '#dcdfe6'
      ctx.beginPath()
      ctx.arc(c.x, c.y, c.r, 0, Math.PI * 2)
      ctx.fill()
      ctx.strokeStyle = '#40434a'
      ctx.lineWidth = 2
      ctx.stroke()

      // Radial ejecta rays
      ctx.strokeStyle = 'rgba(235, 238, 245, 0.25)'
      ctx.lineWidth = 1.5
      for (let i = 0; i < c.rays; i++) {
        const angle = (i * Math.PI * 2) / c.rays
        ctx.beginPath()
        ctx.moveTo(c.x, c.y)
        ctx.lineTo(
          c.x + Math.cos(angle) * c.rayLen,
          c.y + Math.sin(angle) * c.rayLen,
        )
        ctx.stroke()
      }
    }

    // Grid lines: Equator and Prime Meridian (subtle navigation aid)
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.12)'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(0, 256)
    ctx.lineTo(1024, 256) // Equator (0° lat)
    ctx.moveTo(512, 0)
    ctx.lineTo(512, 512) // Prime Meridian (0° lon)
    ctx.stroke()
  }

  const texture = new THREE.CanvasTexture(canvas)
  texture.wrapS = THREE.RepeatWrapping
  texture.wrapT = THREE.ClampToEdgeWrapping
  return texture
}

/**
 * Camera controller supporting orbit rotation, damping, and programmatic view presets.
 */
interface ControlsProps {
  cameraTarget: [number, number, number] | null
}

const CameraControls: React.FC<ControlsProps> = ({ cameraTarget }) => {
  const { camera, gl } = useThree()
  const controlsRef = useRef<OrbitControls | null>(null)

  useEffect(() => {
    // Ensure domElement has ownerDocument in jsdom test environments
    if (typeof window === 'undefined' || !gl.domElement?.ownerDocument) {
      return
    }

    const controls = new OrbitControls(camera, gl.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.08
    controls.minDistance = 3.2
    controls.maxDistance = 22.0
    controlsRef.current = controls

    return () => {
      controls.dispose()
    }
  }, [camera, gl])

  useEffect(() => {
    if (cameraTarget && controlsRef.current) {
      camera.position.set(...cameraTarget)
      camera.lookAt(0, 0, 0)
      controlsRef.current.target.set(0, 0, 0)
      controlsRef.current.update()
    }
  }, [cameraTarget, camera])

  useFrame(() => {
    controlsRef.current?.update()
  })

  return null
}

/**
 * Communication Link Component (Task 3):
 * Renders the line from Earth representation to selected lunar site.
 * Controlled strictly by backend Earth visibility.
 */
interface CommLinkProps {
  earthPos: THREE.Vector3
  sitePos: THREE.Vector3
  visible: boolean | null
}

const CommunicationLink: React.FC<CommLinkProps> = ({ earthPos, sitePos, visible }) => {
  const pulseRef = useRef<THREE.Mesh>(null)
  const lineGeo = useMemo(() => {
    return new THREE.BufferGeometry().setFromPoints([earthPos, sitePos])
  }, [earthPos, sitePos])

  // Restrained traveling pulse along the line when visible === true
  useFrame(({ clock }) => {
    if (visible === true && pulseRef.current) {
      const t = (clock.getElapsedTime() * 0.45) % 1.0
      pulseRef.current.position.lerpVectors(earthPos, sitePos, t)
    }
  })

  if (visible === null) {
    return null
  }

  if (visible === false) {
    // Inactive / Blocked link: Dashed gray line, no traveling pulse
    return (
      <group data-testid="comm-link-blocked">
        <primitive
          object={
            new THREE.Line(
              lineGeo,
              new THREE.LineDashedMaterial({
                color: '#666666',
                dashSize: 0.3,
                gapSize: 0.2,
                linewidth: 1,
              }),
            )
          }
        />
      </group>
    )
  }

  // Active link: Glowing cyan/white line with travelling signal pulse
  return (
    <group data-testid="comm-link-active">
      {/* Main beam */}
      <primitive
        object={
          new THREE.Line(
            lineGeo,
            new THREE.LineBasicMaterial({
              color: '#00f0ff',
              linewidth: 2,
              transparent: true,
              opacity: 0.85,
            }),
          )
        }
      />
      {/* Travelling signal pulse */}
      <mesh ref={pulseRef} position={earthPos}>
        <sphereGeometry args={[0.08, 16, 16]} />
        <meshBasicMaterial color="#ffffff" />
      </mesh>
    </group>
  )
}

/**
 * Site Marker on the Lunar Sphere Surface (Task 1).
 */
interface MarkerProps {
  site: Site
  isSelected: boolean
  onClick: (site: Site) => void
}

const GlobalSiteMarker: React.FC<MarkerProps> = ({ site, isSelected, onClick }) => {
  const { camera } = useThree()
  const [isFarSide, setIsFarSide] = useState(false)

  const pos = useMemo(() => {
    const p = latLonToGlobalScene(
      { latitude: site.latitude, longitude: site.longitude },
      MOON_RADIUS * 1.012,
    )
    return new THREE.Vector3(p.x, p.y, p.z)
  }, [site.latitude, site.longitude])

  useFrame(() => {
    // Normal vector from Moon center at marker
    const normal = pos.clone().normalize()
    // Vector from marker to camera
    const toCamera = camera.position.clone().sub(pos).normalize()
    // Dot product < 0 means the marker points away from camera (occluded / far-side)
    setIsFarSide(normal.dot(toCamera) < -0.05)
  })

  const markerColor = useMemo(() => {
    if (isSelected) return '#ffd700'
    switch (site.category) {
      case 'artemis':
        return '#00f0ff'
      case 'apollo':
        return '#ffc53d'
      case 'clps':
        return '#52c41a'
      default:
        return '#b37feb'
    }
  }, [isSelected, site.category])

  return (
    <group
      position={pos}
      onClick={(e) => {
        e.stopPropagation()
        onClick(site)
      }}
      data-testid={`global-marker-${site.id}`}
    >
      {/* Target ring for selected site */}
      {isSelected && (
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.09, 0.13, 32]} />
          <meshBasicMaterial color="#ffd700" side={THREE.DoubleSide} />
        </mesh>
      )}

      {/* Center dot */}
      <mesh>
        <sphereGeometry args={[isSelected ? 0.065 : 0.04, 16, 16]} />
        <meshBasicMaterial
          color={markerColor}
          transparent={isFarSide}
          opacity={isFarSide ? 0.35 : 1.0}
        />
      </mesh>
    </group>
  )
}

/**
 * Scene Content with Spherical Moon, Celestial Vectors, and Comm Link.
 */
interface SceneContentProps {
  catalogSites?: Site[] | null
  selectedSite?: ResolvedSite | Site | null
  selectedCoordinate?: LunarCoordinate | null
  onSelectCoordinate?: (coord: LunarCoordinate) => void
  onSelectSite?: (site: Site) => void
  observationPoint?: GlobalMoonSceneProps['observationPoint']
  cameraPreset: [number, number, number] | null
}

const GlobalSceneContent: React.FC<SceneContentProps> = ({
  catalogSites,
  selectedSite,
  selectedCoordinate,
  onSelectCoordinate,
  onSelectSite,
  observationPoint,
  cameraPreset,
}) => {
  const moonTexture = useMemo(() => createProceduralMoonTexture(), [])

  // Selected site position in global scene coordinates
  const sitePos = useMemo(() => {
    const lat = selectedSite?.latitude ?? selectedCoordinate?.latitude ?? -89.44
    const lon = selectedSite?.longitude ?? selectedCoordinate?.longitude ?? -137.9
    const p = latLonToGlobalScene({ latitude: lat, longitude: lon }, MOON_RADIUS * 1.01)
    return new THREE.Vector3(p.x, p.y, p.z)
  }, [selectedSite, selectedCoordinate])

  // Sun and Earth directions in global Moon-fixed frame (Task 2)
  const { sunPos, earthPos, earthVisible } = useMemo(() => {
    if (!observationPoint) {
      return { sunPos: null, earthPos: null, earthVisible: null }
    }

    const lat = selectedSite?.latitude ?? selectedCoordinate?.latitude ?? 0
    const lon = selectedSite?.longitude ?? selectedCoordinate?.longitude ?? 0
    const coord: LunarCoordinate = { latitude: lat, longitude: lon }

    // Convert local ENU to global Moon-fixed Cartesian frame
    const sunMcmf = enuToMoonFixed(observationPoint.sun.direction_enu, coord)
    const sunSceneDir = moonFixedToGlobalScene(sunMcmf)
    const sPos = new THREE.Vector3(
      sunSceneDir.x * SUN_DISTANCE,
      sunSceneDir.y * SUN_DISTANCE,
      sunSceneDir.z * SUN_DISTANCE,
    )

    const earthMcmf = enuToMoonFixed(observationPoint.earth.direction_enu, coord)
    const earthSceneDir = moonFixedToGlobalScene(earthMcmf)
    const ePos = new THREE.Vector3(
      earthSceneDir.x * EARTH_DISTANCE,
      earthSceneDir.y * EARTH_DISTANCE,
      earthSceneDir.z * EARTH_DISTANCE,
    )

    return {
      sunPos: sPos,
      earthPos: ePos,
      earthVisible: observationPoint.earth.visible,
    }
  }, [observationPoint, selectedSite, selectedCoordinate])

  const handleGlobeClick = useCallback(
    (e: { point: THREE.Vector3; stopPropagation: () => void }) => {
      e.stopPropagation()
      if (!onSelectCoordinate) return

      // Convert clicked point back to lat/lon
      const normP = e.point.clone().normalize()
      // scene.y = z_mcmf = sin(lat)
      const clampedY = Math.max(-1.0, Math.min(1.0, normP.y))
      const latDeg = (Math.asin(clampedY) * 180.0) / Math.PI
      // scene.x = cos(lat)*cos(lon), scene.z = -cos(lat)*sin(lon)
      const lonRad = Math.atan2(-normP.z, normP.x)
      const lonDeg = normalizeLongitude((lonRad * 180.0) / Math.PI)

      onSelectCoordinate({ latitude: Math.round(latDeg * 100) / 100, longitude: lonDeg })
    },
    [onSelectCoordinate],
  )

  return (
    <>
      <CameraControls cameraTarget={cameraPreset} />

      {/* Lighting: Ambient + Directional Sun */}
      <ambientLight intensity={sunPos ? 0.25 : 0.6} color="#dbe2ef" />
      {sunPos && (
        <directionalLight
          position={sunPos}
          intensity={2.8}
          color="#fff8e7"
          castShadow
        />
      )}

      {/* Spherical Moon */}
      <mesh
        data-testid="global-moon-sphere"
        onClick={handleGlobeClick}
      >
        <sphereGeometry args={[MOON_RADIUS, 64, 64]} />
        <meshStandardMaterial
          map={moonTexture}
          roughness={0.92}
          metalness={0.04}
        />
      </mesh>

      {/* Selected location marker highlight */}
      <mesh position={sitePos}>
        <sphereGeometry args={[0.07, 16, 16]} />
        <meshBasicMaterial color="#ffc53d" />
      </mesh>

      {/* Catalog site markers */}
      {catalogSites?.map((site) => {
        const isSelected =
          (selectedSite && 'id' in selectedSite && selectedSite.id === site.id) ||
          (selectedSite &&
            'site_id' in selectedSite &&
            selectedSite.site_id === site.id)
        return (
          <GlobalSiteMarker
            key={site.id}
            site={site}
            isSelected={Boolean(isSelected)}
            onClick={(s) => {
              onSelectSite?.(s)
              onSelectCoordinate?.({
                latitude: s.latitude,
                longitude: s.longitude,
              })
            }}
          />
        )
      })}

      {/* Sun Representation */}
      {sunPos && (
        <group position={sunPos} data-testid="global-sun-representation">
          <mesh>
            <sphereGeometry args={[0.65, 32, 32]} />
            <meshBasicMaterial color="#fff4cc" />
          </mesh>
          <pointLight color="#fff0b3" intensity={1.5} distance={20} />
        </group>
      )}

      {/* Earth Representation */}
      {earthPos && (
        <group position={earthPos} data-testid="global-earth-representation">
          {/* Earth sphere */}
          <mesh>
            <sphereGeometry args={[0.5, 32, 32]} />
            <meshStandardMaterial
              color="#1a73e8"
              roughness={0.6}
              metalness={0.1}
            />
          </mesh>
          {/* Atmospheric halo */}
          <mesh>
            <sphereGeometry args={[0.54, 32, 32]} />
            <meshBasicMaterial
              color="#80d8ff"
              transparent
              opacity={0.3}
              side={THREE.BackSide}
            />
          </mesh>
        </group>
      )}

      {/* Earth Communication Line (Task 3) */}
      {earthPos && (
        <CommunicationLink
          earthPos={earthPos}
          sitePos={sitePos}
          visible={earthVisible}
        />
      )}
    </>
  )
}

/**
 * Global Moon 3D Viewport Component (Stage 5).
 */
export const GlobalMoonScene: React.FC<GlobalMoonSceneProps> = ({
  className = '',
  catalogSites,
  selectedSite,
  selectedCoordinate,
  onSelectCoordinate,
  onSelectSite,
  observationPoint,
  isLoading = false,
  dataStatus,
  demonstrationMode = false,
  onError,
}) => {
  const [cameraPreset, setCameraPreset] = useState<[number, number, number] | null>(
    DEFAULT_CAMERA_POS,
  )

  const activeCoord = useMemo(() => {
    const lat = selectedSite?.latitude ?? selectedCoordinate?.latitude
    const lon = selectedSite?.longitude ?? selectedCoordinate?.longitude
    if (lat !== undefined && lon !== undefined) {
      return { latitude: lat, longitude: lon }
    }
    return null
  }, [selectedSite, selectedCoordinate])

  const activeObservationPoint = isLoading ? null : observationPoint

  const linkStatus = useMemo(() => {
    if (isLoading) return { label: 'Link: Awaiting ephemeris…', color: '#888' }
    if (!observationPoint) return { label: 'Link: Awaiting observation', color: '#888' }
    if (observationPoint.earth.visible === true) {
      return { label: 'Earth Link: Active (Line of sight open)', color: '#00f0ff' }
    }
    return { label: 'Earth Link: Blocked (No line of sight)', color: '#faad14' }
  }, [isLoading, observationPoint])

  return (
    <div
      className={`global-moon-container ${className}`}
      data-testid="global-moon-container"
      style={{
        position: 'relative',
        width: '100%',
        height: '100%',
        minHeight: '380px',
        backgroundColor: '#0a0a0e',
        borderRadius: '6px',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Demonstration Banner */}
      {demonstrationMode && (
        <div
          data-testid="global-demonstration-banner"
          style={{
            position: 'absolute',
            top: '8px',
            left: '8px',
            zIndex: 10,
            padding: '3px 8px',
            backgroundColor: 'rgba(250, 173, 20, 0.2)',
            border: '1px solid #faad14',
            borderRadius: '4px',
            color: '#faad14',
            fontSize: '0.72rem',
            fontWeight: 600,
          }}
        >
          Demonstration Ephemeris — Not Measured Operations
        </div>
      )}

      {/* Top HUD Controls and Ephemeris Status */}
      <div
        className="global-hud-overlay"
        data-testid="global-hud-overlay"
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          padding: '6px 10px',
          backgroundColor: 'rgba(10, 10, 14, 0.88)',
          borderBottom: '1px solid #1a1a26',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '8px',
          fontSize: '0.75rem',
          color: '#a0a0a0',
          zIndex: 9,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
          <span style={{ color: '#fff', fontWeight: 600 }}>Global Moon</span>
          {activeCoord && (
            <span style={{ color: '#d9d9d9' }} data-testid="global-selected-coord">
              Site: {activeCoord.latitude.toFixed(2)}°, {activeCoord.longitude.toFixed(2)}°
            </span>
          )}
          <span style={{ color: linkStatus.color, fontWeight: 500 }} data-testid="global-link-status">
            {linkStatus.label}
          </span>
          {dataStatus === 'cached' && (
            <span
              style={{
                padding: '1px 4px',
                backgroundColor: 'rgba(24, 144, 255, 0.2)',
                borderRadius: '2px',
                color: '#1890ff',
                fontSize: '0.65rem',
              }}
            >
              cached
            </span>
          )}
        </div>

        {/* View Presets & Camera Reset (Task 1) */}
        <div style={{ display: 'flex', gap: '5px' }}>
          <button
            type="button"
            className="secondary-button"
            style={{ padding: '2px 6px', fontSize: '0.7rem' }}
            onClick={() => setCameraPreset([...DEFAULT_CAMERA_POS])}
            title="Reset to default oblique view"
            data-testid="reset-camera-btn"
          >
            Reset
          </button>
          <button
            type="button"
            className="secondary-button"
            style={{ padding: '2px 6px', fontSize: '0.7rem' }}
            onClick={() => setCameraPreset([...SOUTH_POLE_CAMERA_POS])}
            title="View lunar South Pole"
          >
            South Pole
          </button>
          <button
            type="button"
            className="secondary-button"
            style={{ padding: '2px 6px', fontSize: '0.7rem' }}
            onClick={() => setCameraPreset([...NEAR_SIDE_CAMERA_POS])}
            title="View Near Side (0° lon)"
          >
            Near Side
          </button>
          <button
            type="button"
            className="secondary-button"
            style={{ padding: '2px 6px', fontSize: '0.7rem' }}
            onClick={() => setCameraPreset([...FAR_SIDE_CAMERA_POS])}
            title="View Far Side (180° lon)"
          >
            Far Side
          </button>
        </div>
      </div>

      {/* 3D WebGL Canvas with Error Isolation */}
      <div style={{ position: 'relative', flex: 1, width: '100%' }}>
        <SceneErrorBoundary onError={onError}>
          <Suspense
            fallback={
              <div style={{ color: '#888', padding: '1rem' }}>
                Initializing global Moon…
              </div>
            }
          >
            <Canvas
              camera={{ position: DEFAULT_CAMERA_POS, fov: 42 }}
              style={{ width: '100%', height: '100%' }}
              data-testid="global-moon-canvas"
            >
              <GlobalSceneContent
                catalogSites={catalogSites}
                selectedSite={selectedSite}
                selectedCoordinate={selectedCoordinate}
                onSelectCoordinate={onSelectCoordinate}
                onSelectSite={onSelectSite}
                observationPoint={activeObservationPoint}
                cameraPreset={cameraPreset}
              />
            </Canvas>
          </Suspense>
        </SceneErrorBoundary>
      </div>

      {/* Accessible site list & link status overlay */}
      <div
        data-testid="global-accessibility-overlay"
        style={{
          position: 'absolute',
          bottom: '28px',
          left: '10px',
          right: '10px',
          zIndex: 8,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-end',
          pointerEvents: 'none',
        }}
      >
        {/* Catalog site markers selector for keyboard accessibility and test queries */}
        {catalogSites && catalogSites.length > 0 && (
          <div
            data-testid="global-site-markers-list"
            style={{ display: 'flex', gap: '4px', flexWrap: 'wrap', pointerEvents: 'auto', maxWidth: '70%' }}
          >
            {catalogSites.map((site) => {
              const isSelected =
                (selectedSite && 'id' in selectedSite && selectedSite.id === site.id) ||
                (selectedSite && 'site_id' in selectedSite && selectedSite.site_id === site.id)
              return (
                <button
                  key={site.id}
                  type="button"
                  data-testid={`global-marker-${site.id}`}
                  className={isSelected ? 'primary-button' : 'secondary-button'}
                  style={{ padding: '2px 6px', fontSize: '0.65rem' }}
                  onClick={() => {
                    onSelectSite?.(site)
                    onSelectCoordinate?.({
                      latitude: site.latitude,
                      longitude: site.longitude,
                    })
                  }}
                >
                  {site.name}
                </button>
              )
            })}
          </div>
        )}

        {/* Link indicator representation in DOM */}
        {activeObservationPoint && (
          <div
            data-testid={activeObservationPoint.earth.visible ? 'comm-link-active' : 'comm-link-blocked'}
            style={{
              padding: '2px 8px',
              backgroundColor: 'rgba(10, 10, 14, 0.85)',
              border: `1px solid ${activeObservationPoint.earth.visible ? '#00f0ff' : '#666'}`,
              borderRadius: '3px',
              fontSize: '0.7rem',
              color: activeObservationPoint.earth.visible ? '#00f0ff' : '#aaa',
              pointerEvents: 'auto',
            }}
          >
            {activeObservationPoint.earth.visible ? 'Signal link active' : 'Signal link blocked'}
          </div>
        )}
      </div>

      {/* Provenance and Legend Footer */}
      <div
        className="global-moon-footer"
        data-testid="global-moon-footer"
        style={{
          padding: '4px 10px',
          backgroundColor: '#0c0d12',
          borderTop: '1px solid #1a1a24',
          fontSize: '0.65rem',
          color: '#656575',
          display: 'flex',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '4px',
        }}
      >
        <span>
          MCMF global frame · Sphere radius 1,737.4 km reference · Drag to orbit, scroll to zoom
        </span>
        <span>Backend Earth visibility authoritative · Link line is a visual aid</span>
      </div>

      {/* Loading Overlay */}
      {isLoading && (
        <div
          data-testid="global-scene-loading"
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(10, 10, 14, 0.75)',
            zIndex: 20,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#d9d9d9',
            fontSize: '0.9rem',
          }}
        >
          Loading global observation ephemeris…
        </div>
      )}
    </div>
  )
}
