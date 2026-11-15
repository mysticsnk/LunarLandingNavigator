import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeAll, afterAll } from 'vitest'
import { GlobalMoonScene } from './GlobalMoonScene'
import {
  enuToMoonFixed,
  moonFixedToGlobalScene,
  latLonToGlobalScene,
  azimuthElevationToEnu,
} from '../../lib/coordinates'
import type { ObservationPoint } from './types'
import type { Site } from '../../api/types'

// Polyfill ResizeObserver for jsdom environment
beforeAll(() => {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
})

afterAll(() => {
  delete (globalThis as unknown as { ResizeObserver?: unknown }).ResizeObserver
})

const mockSites: Site[] = [
  {
    id: 'shackleton-connecting-ridge',
    name: 'Shackleton Connecting Ridge',
    category: 'artemis',
    latitude: -89.44,
    longitude: -137.9,
    description: 'Artemis candidate ridge near south pole.',
    source_url: 'https://example.org/shackleton',
    quickmap_url: 'https://example.org/quickmap-shackleton',
    terrain_region_id: 'shackleton_connecting_ridge',
  },
  {
    id: 'apollo-11',
    name: 'Apollo 11 Tranquility Base',
    category: 'apollo',
    latitude: 0.674,
    longitude: 23.473,
    description: 'First crewed lunar landing.',
    source_url: 'https://example.org/apollo11',
    quickmap_url: 'https://example.org/quickmap-apollo11',
    terrain_region_id: null,
  },
  {
    id: 'far-side-crater',
    name: 'Tsiolkovskiy Crater',
    category: 'international',
    latitude: -20.4,
    longitude: 129.1,
    description: 'Prominent far side crater with dark basalt floor.',
    source_url: 'https://example.org/tsiolkovskiy',
    quickmap_url: 'https://example.org/quickmap-tsiolkovskiy',
    terrain_region_id: null,
  },
]

describe('Stage 5 GlobalMoonScene Component', () => {
  describe('Global Scene Structure & Controls', () => {
    it('renders the global moon container, HUD, footer, and canvas', () => {
      render(<GlobalMoonScene />)

      expect(screen.getByTestId('global-moon-container')).toBeInTheDocument()
      expect(screen.getByTestId('global-hud-overlay')).toBeInTheDocument()
      expect(screen.getByTestId('global-moon-canvas')).toBeInTheDocument()
      expect(screen.getByTestId('global-moon-footer')).toHaveTextContent(
        /MCMF global frame · Sphere radius 1,737.4 km reference/i,
      )
    })

    it('renders camera reset and view preset buttons', () => {
      render(<GlobalMoonScene />)

      expect(screen.getByTestId('reset-camera-btn')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'South Pole' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Near Side' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Far Side' })).toBeInTheDocument()

      // Clicking reset camera button triggers state change without throwing
      fireEvent.click(screen.getByTestId('reset-camera-btn'))
      fireEvent.click(screen.getByRole('button', { name: 'South Pole' }))
    })

    it('displays loading overlay when isLoading is true', () => {
      render(<GlobalMoonScene isLoading={true} />)
      expect(screen.getByTestId('global-scene-loading')).toBeInTheDocument()
      expect(
        screen.getByText(/Loading global observation ephemeris…/i),
      ).toBeInTheDocument()
    })

    it('displays demonstration badge when demonstrationMode is true', () => {
      render(<GlobalMoonScene demonstrationMode={true} />)
      expect(screen.getByTestId('global-demonstration-banner')).toBeInTheDocument()
      expect(
        screen.getByText(/Demonstration Ephemeris — Not Measured Operations/i),
      ).toBeInTheDocument()
    })
  })

  describe('Site Marker Synchronization & Coordinate Transformation', () => {
    it('renders catalog site markers and allows site selection', () => {
      const handleSelectSite = vi.fn()
      const handleSelectCoord = vi.fn()

      render(
        <GlobalMoonScene
          catalogSites={mockSites}
          selectedSite={mockSites[0]}
          onSelectSite={handleSelectSite}
          onSelectCoordinate={handleSelectCoord}
        />,
      )

      expect(
        screen.getByTestId('global-marker-shackleton-connecting-ridge'),
      ).toBeInTheDocument()
      expect(screen.getByTestId('global-marker-apollo-11')).toBeInTheDocument()
      expect(screen.getByTestId('global-marker-far-side-crater')).toBeInTheDocument()

      // Click on Apollo 11 marker
      fireEvent.click(screen.getByTestId('global-marker-apollo-11'))
      expect(handleSelectSite).toHaveBeenCalledWith(mockSites[1])
      expect(handleSelectCoord).toHaveBeenCalledWith({
        latitude: mockSites[1].latitude,
        longitude: mockSites[1].longitude,
      })
    })

    it('verifies coordinate mapping for high latitudes and longitude wrap', () => {
      // Shackleton rim: -89.44°, 222.1°
      const p1 = latLonToGlobalScene({ latitude: -89.44, longitude: 222.1 }, 2.5)
      // Normalized longitude: -137.9°
      const p2 = latLonToGlobalScene({ latitude: -89.44, longitude: -137.9 }, 2.5)

      // Equivalent longitudes produce identical global scene positions
      expect(p1.x).toBeCloseTo(p2.x, 6)
      expect(p1.y).toBeCloseTo(p2.y, 6)
      expect(p1.z).toBeCloseTo(p2.z, 6)

      // High south-polar latitude is mapped near the bottom (-Y)
      expect(p1.y).toBeLessThan(-2.49)
    })
  })

  describe('Actual Sun and Earth Directions (Task 2)', () => {
    it('computes global MCMF vectors from returned topocentric ENU directions', () => {
      const site = { latitude: -89.44, longitude: -137.9 }
      const sunEnu = azimuthElevationToEnu(180, 1.5) // Sun at Az 180°, El 1.5°
      const earthEnu = azimuthElevationToEnu(0, 3.2) // Earth at Az 0°, El 3.2°

      const sunMcmf = enuToMoonFixed(sunEnu, site)
      const earthMcmf = enuToMoonFixed(earthEnu, site)

      // Both vectors are unit length in MCMF
      expect(Math.hypot(sunMcmf.x, sunMcmf.y, sunMcmf.z)).toBeCloseTo(1.0, 5)
      expect(Math.hypot(earthMcmf.x, earthMcmf.y, earthMcmf.z)).toBeCloseTo(1.0, 5)

      // Mapping to Three.js global scene maintains unit length and right-handed orientation
      const sunScene = moonFixedToGlobalScene(sunMcmf)
      const earthScene = moonFixedToGlobalScene(earthMcmf)

      expect(Math.hypot(sunScene.x, sunScene.y, sunScene.z)).toBeCloseTo(1.0, 5)
      expect(Math.hypot(earthScene.x, earthScene.y, earthScene.z)).toBeCloseTo(1.0, 5)
    })
  })

  describe('Authoritative Communication Link States (Task 3)', () => {
    it('shows active communication link when backend reports earth.visible === true', () => {
      const point: ObservationPoint = {
        timestamp: '2026-11-15T12:00:00Z',
        sun: {
          azimuth_deg: 180.0,
          elevation_deg: 2.0,
          horizon_elevation_deg: 0.0,
          visible: true,
          direction_enu: azimuthElevationToEnu(180, 2.0),
        },
        earth: {
          azimuth_deg: 10.0,
          elevation_deg: 4.5,
          horizon_elevation_deg: 0.0,
          visible: true, // Line of sight open
          direction_enu: azimuthElevationToEnu(10, 4.5),
        },
        is_golden_window: true,
      }

      render(
        <GlobalMoonScene
          observationPoint={point}
          selectedSite={mockSites[0]}
        />,
      )

      expect(screen.getByTestId('comm-link-active')).toBeInTheDocument()
      expect(screen.queryByTestId('comm-link-blocked')).not.toBeInTheDocument()
      expect(screen.getByTestId('global-link-status')).toHaveTextContent(
        /Earth Link: Active \(Line of sight open\)/i,
      )
    })

    it('shows inactive dashed gray link when backend reports earth.visible === false', () => {
      const point: ObservationPoint = {
        timestamp: '2026-11-15T12:00:00Z',
        sun: {
          azimuth_deg: 180.0,
          elevation_deg: 2.0,
          horizon_elevation_deg: 0.0,
          visible: true,
          direction_enu: azimuthElevationToEnu(180, 2.0),
        },
        earth: {
          azimuth_deg: 10.0,
          elevation_deg: -1.5,
          horizon_elevation_deg: 0.0,
          visible: false, // Line of sight blocked
          direction_enu: azimuthElevationToEnu(10, -1.5),
        },
        is_golden_window: false,
      }

      render(
        <GlobalMoonScene
          observationPoint={point}
          selectedSite={mockSites[0]}
        />,
      )

      expect(screen.getByTestId('comm-link-blocked')).toBeInTheDocument()
      expect(screen.queryByTestId('comm-link-active')).not.toBeInTheDocument()
      expect(screen.getByTestId('global-link-status')).toHaveTextContent(
        /Earth Link: Blocked \(No line of sight\)/i,
      )
    })

    it('does not render active link when ephemeris is unknown or loading', () => {
      render(
        <GlobalMoonScene
          observationPoint={null}
          isLoading={true}
          selectedSite={mockSites[0]}
        />,
      )

      expect(screen.queryByTestId('comm-link-active')).not.toBeInTheDocument()
      expect(screen.queryByTestId('comm-link-blocked')).not.toBeInTheDocument()
      expect(screen.getByTestId('global-link-status')).toHaveTextContent(
        /Link: Awaiting ephemeris…/i,
      )
    })
  })
})
