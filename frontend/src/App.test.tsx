import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { VERIFIED_MAP_LAYERS } from './features/map/layers'
import { App } from './App'
import { apiClient } from './api/client'
import { ApiClientError } from './api/errors'
import {
  accepted,
  catalog,
  observationResult,
  resources,
  succeeded,
  timelineAccepted,
  timelineResult,
} from './test/fixtures'
import type { LunarMapProps } from './features/map'
import type { LunarSceneProps } from './features/scene'
import { useHeightmap } from './features/scene'

const visual = vi.hoisted(() => ({ map: vi.fn(), scene: vi.fn() }))
vi.mock('./features/map', () => ({
  LunarMap: (props: LunarMapProps) => {
    visual.map(props)
    return (
      <button
        type="button"
        onClick={() =>
          props.onSelectCoordinate?.({ latitude: -88, longitude: 25 })
        }
      >
        Select test map coordinate
      </button>
    )
  },
}))
vi.mock('./features/scene', () => ({
  LunarScene: (props: LunarSceneProps) => {
    visual.scene(props)
    return <div data-testid="scene-integration" />
  },
  useHeightmap: vi.fn(() => ({
    heightmap: null,
    loading: false,
    error: null,
    reload: vi.fn(),
  })),
}))

beforeEach(() => {
  vi.spyOn(apiClient, 'getMapLayers').mockResolvedValue({
    items: VERIFIED_MAP_LAYERS,
  })
  vi.spyOn(apiClient, 'getHealth').mockResolvedValue({
    status: 'healthy',
    service: 'lunar-navigator-api',
    database: 'ok',
    timestamp: '2026-11-14T10:00:00Z',
  })
  vi.spyOn(apiClient, 'getSites').mockResolvedValue(catalog)
  vi.spyOn(apiClient, 'getTerrainCoverage').mockResolvedValue({
    available: true, latitude: -89.44, longitude: -137.9, region_id: 'test-region',
    dataset_id: 'test-dem-v1', resolution_m: 20, source_url: 'https://example.org/dem', reason: null,
  })
  vi.spyOn(apiClient, 'getResources').mockResolvedValue(resources)
  vi.spyOn(apiClient, 'submitNow').mockResolvedValue(accepted)
  vi.spyOn(apiClient, 'getJob').mockResolvedValue(succeeded)
  vi.spyOn(apiClient, 'getResult').mockResolvedValue(observationResult)
  vi.spyOn(apiClient, 'submitTimeline').mockResolvedValue(timelineAccepted)
  vi.spyOn(apiClient, 'getTimelineResult').mockResolvedValue({
    ...timelineResult,
    summary: { ...timelineResult.summary, next_sunset_at: null, next_earthset_at: null },
  })
})
afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
  visual.map.mockClear()
  visual.scene.mockClear()
})

async function selectCatalog() {
  await screen.findByRole('option', { name: 'Synthetic catalog site' })
  fireEvent.change(screen.getByLabelText('Catalog site'), {
    target: { value: 'development-site' },
  })
  fireEvent.change(screen.getByLabelText('Observation date and time (UTC)'), {
    target: { value: '2027-07-15T00:00:00' },
  })
}

describe('Stage 4 observation workspace', () => {
  it('does not replace a failed layer catalog with static operational imagery', async () => {
    vi.mocked(apiClient.getMapLayers)
      .mockRejectedValueOnce(
        new ApiClientError({
          code: 'NETWORK_ERROR',
          message: 'Layer catalog unreachable',
        }),
      )
      .mockResolvedValueOnce({ items: VERIFIED_MAP_LAYERS })
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Layer catalog unreachable',
    )
    expect(visual.map).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Retry map layers' }))
    await waitFor(() => expect(visual.map).toHaveBeenCalled())
    expect(visual.map.mock.lastCall![0].layers).toEqual(VERIFIED_MAP_LAYERS)
  })
  it('starts with unknown operational values and no fabricated directions', async () => {
    const { container } = render(<App />)
    expect(screen.getByTestId('app-title')).toHaveTextContent(
      'Lunar Landing Site Navigator',
    )
    expect(screen.getByText('Stage 4')).toBeInTheDocument()
    expect(screen.getByText(/Sun visibility: Unknown/)).toBeInTheDocument()
    expect(screen.getByText('Simultaneous availability: Unknown')).toBeInTheDocument()
    expect(visual.scene.mock.lastCall![0]).toMatchObject({
      sunDirectionEnu: null,
      earthDirectionEnu: null,
    })
    expect(container.textContent).not.toMatch(/\d+\s*(%|watts|mbps)/i)
    expect(apiClient.submitNow).not.toHaveBeenCalled()
    await screen.findByText('No matching articles in the available feed.')
  })
  it('submits a catalog ID with an explicit UTC timestamp and source links', async () => {
    render(<App />)
    await selectCatalog()
    expect(
      screen.getByRole('link', { name: /Official site source/ }),
    ).toHaveAttribute('href', catalog.items[0].source_url)
    expect(screen.getByRole('link', { name: /QuickMap/ })).toHaveAttribute(
      'href',
      catalog.items[0].quickmap_url,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Request observation' }))
    await waitFor(() =>
      expect(apiClient.submitNow).toHaveBeenCalledWith(
        {
          site: { site_id: 'development-site' },
          target_time: '2027-07-15T00:00:00Z',
          horizon_mode: 'geometric',
          observer_height_m: 2,
          visibility_margin_deg: 0,
        },
        expect.any(Object),
      ),
    )
    expect(
      await screen.findByText('Queued — waiting for the worker'),
    ).toBeInTheDocument()
  })
  it('loads timeline intervals and drives the scene from the selected returned sample', async () => {
    vi.mocked(apiClient.getJob).mockResolvedValue({
      ...succeeded,
      kind: 'timeline',
    })
    render(<App />)
    await selectCatalog()
    vi.useFakeTimers()
    fireEvent.click(screen.getByRole('radio', { name: 'Timeline' }))
    fireEvent.change(screen.getByLabelText('Duration (days)'), {
      target: { value: '14' },
    })
    fireEvent.change(screen.getByLabelText('Time step (minutes)'), {
      target: { value: '120' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Request timeline' }))
    expect(apiClient.submitTimeline).toHaveBeenCalledWith(
      {
        site: { site_id: 'development-site' },
        start_time: '2027-07-15T00:00:00Z',
        duration_days: 14,
        step_minutes: 120,
        horizon_mode: 'geometric',
        observer_height_m: 2,
        visibility_margin_deg: 0,
      },
      expect.any(Object),
    )
    await act(async () => vi.advanceTimersByTimeAsync(2000))
    expect(screen.getByText('4 returned samples · 360-minute resolution · geometric horizon')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Result provenance'))
    const provenance = screen.getByText('Result provenance').parentElement!
    expect(within(provenance).getByText('development-fixture-v1')).toBeInTheDocument()
    expect(within(provenance).getByText('2027-07-15T00:00:00Z')).toBeInTheDocument()
    expect(screen.getAllByText(/Window 1/)).toHaveLength(3)
    expect(screen.getByText('Continues through period end (clipped)')).toBeInTheDocument()
    expect(screen.getAllByText(/No set event observed in this computed period\./)).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: 'Next sample' }))
    expect(screen.getByText('2027-07-15T06:00:00Z (UTC)')).toBeInTheDocument()
    expect(visual.scene.mock.lastCall![0].observationPoint).toEqual(timelineResult.points[1])
    expect(apiClient.submitTimeline).toHaveBeenCalledTimes(1)
    expect(apiClient.submitNow).not.toHaveBeenCalled()
  })
  it('submits custom coordinates without a catalog ID and never clamps invalid latitude', async () => {
    render(<App />)
    await selectCatalog()
    fireEvent.click(screen.getByLabelText('Custom coordinates'))
    fireEvent.change(screen.getByLabelText('Latitude (°)'), {
      target: { value: '91' },
    })
    fireEvent.change(screen.getByLabelText('Longitude (° east)'), {
      target: { value: '222.1' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Request observation' }))
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Latitude must be -90 to 90',
    )
    expect(screen.getByLabelText('Latitude (°)')).toHaveValue(91)
    expect(apiClient.submitNow).not.toHaveBeenCalled()
    expect(visual.map.mock.lastCall![0].selectedCoordinate).toBeNull()
    fireEvent.change(screen.getByLabelText('Latitude (°)'), {
      target: { value: '-89.44' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Request observation' }))
    await waitFor(() => expect(apiClient.submitNow).toHaveBeenCalled())
    expect(vi.mocked(apiClient.submitNow).mock.calls[0][0].site).toEqual({
      latitude: -89.44,
      longitude: 222.1,
    })
  })
  it('shares map selection with the custom form without transforming coordinates', async () => {
    render(<App />)
    await selectCatalog()
    fireEvent.click(
      screen.getByRole('button', { name: 'Select test map coordinate' }),
    )
    expect(screen.getByLabelText('Custom coordinates')).toBeChecked()
    expect(screen.getByLabelText('Latitude (°)')).toHaveValue(-88)
    expect(screen.getByLabelText('Longitude (° east)')).toHaveValue(25)
    expect(visual.map.mock.lastCall![0]).toMatchObject({
      selectedCoordinate: { latitude: -88, longitude: 25 },
      selectedSiteId: null,
    })
  })
  it('filters and paginates the server catalog', async () => {
    vi.mocked(apiClient.getSites).mockResolvedValue({ ...catalog, total: 51 })
    render(<App />)
    await selectCatalog()
    fireEvent.click(screen.getByRole('button', { name: 'Next sites' }))
    await waitFor(() =>
      expect(apiClient.getSites).toHaveBeenLastCalledWith(
        { limit: 50, offset: 50 },
        expect.any(Object),
      ),
    )
    fireEvent.change(screen.getByLabelText('Category'), {
      target: { value: 'apollo' },
    })
    await waitFor(() =>
      expect(apiClient.getSites).toHaveBeenLastCalledWith(
        { category: 'apollo', limit: 50, offset: 0 },
        expect.any(Object),
      ),
    )
    expect(screen.getByLabelText('Catalog site')).toHaveValue('')
  })
  it('displays actual returned values and provenance, integrates ENU vectors, and keeps the old result tied to its scenario on edit', async () => {
    vi.mocked(apiClient.getResult).mockResolvedValue({
      ...observationResult,
      meta: { ...observationResult.meta, data_status: 'cached' },
    })
    render(<App />)
    await selectCatalog()
    vi.useFakeTimers()
    await act(async () => {
      fireEvent.click(
        screen.getByRole('button', { name: 'Request observation' }),
      )
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    expect(screen.getByText('Observation ready')).toBeInTheDocument()
    const section = screen.getByRole('region', { name: 'Observation' })
    expect(within(section).getByText('cached')).toBeInTheDocument()
    expect(
      within(section).getByText('Synthetic development site'),
    ).toBeInTheDocument()
    expect(
      within(section).getByText(/-89.44° latitude, -137.9° east/),
    ).toBeInTheDocument()
    expect(
      within(section).getByText('2027-07-15T00:00:00Z (UTC)'),
    ).toBeInTheDocument()
    expect(within(section).getAllByRole('cell', { name: '30°' })).toHaveLength(
      2,
    )
    expect(within(section).getAllByRole('cell', { name: 'Yes' })).toHaveLength(
      2,
    )
    expect(
      within(section).getByText('development-fixture-v1'),
    ).toBeInTheDocument()
    expect(
      within(section).getByRole('link', { name: /Synthetic fixture/ }),
    ).toHaveAttribute('href', observationResult.meta.sources[0].url)
    expect(visual.scene.mock.lastCall![0]).toMatchObject({
      sunDirectionEnu: observationResult.point.sun.direction_enu,
      earthDirectionEnu: observationResult.point.earth.direction_enu,
      observerHeightM: 2,
      observationPoint: observationResult.point,
      dataStatus: 'cached',
      site: observationResult.site,
    })
    fireEvent.change(screen.getByLabelText('Observer height (m)'), {
      target: { value: '3' },
    })
    expect(screen.getByText('Synthetic development site')).toBeInTheDocument()
    expect(screen.getByText(/Displayed result uses geometric mode/)).toBeInTheDocument()
    expect(screen.getByText(/Simultaneous availability:/)).toBeInTheDocument()
    expect(visual.scene.mock.lastCall![0]).toMatchObject({
      sunDirectionEnu: observationResult.point.sun.direction_enu,
      earthDirectionEnu: observationResult.point.earth.direction_enu,
    })
  })
  it('checks terrain coverage, submits only an explicit supported terrain request, and does not fall back', async () => {
    render(<App />)
    await selectCatalog()
    fireEvent.change(screen.getByLabelText('Horizon mode'), { target: { value: 'terrain' } })
    expect(await screen.findByText(/Terrain supported.*test-dem-v1.*20 m/)).toBeInTheDocument()
    expect(vi.mocked(useHeightmap)).toHaveBeenLastCalledWith('test-region')
    fireEvent.change(screen.getByLabelText('Observer height (m)'), { target: { value: '3' } })
    expect(screen.getByText(/Terrain supported.*test-dem-v1.*20 m/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Request observation' }))
    await waitFor(() => expect(apiClient.submitNow).toHaveBeenCalledWith(expect.objectContaining({ horizon_mode: 'terrain', observer_height_m: 3 }), expect.any(Object)))
  })
  it.each([
    ['unsupported', { available: false, latitude: -89.44, longitude: -137.9, region_id: null, dataset_id: null, resolution_m: null, source_url: null, reason: 'outside_coverage' }],
    ['failed', new ApiClientError({ code: 'NETWORK_ERROR', message: 'coverage down' })],
  ] as const)('blocks terrain submission on %s coverage without changing mode', async (_state, coverageResult) => {
    if (coverageResult instanceof Error) vi.mocked(apiClient.getTerrainCoverage).mockRejectedValue(coverageResult)
    else vi.mocked(apiClient.getTerrainCoverage).mockResolvedValue(coverageResult)
    render(<App />)
    await selectCatalog()
    fireEvent.change(screen.getByLabelText('Horizon mode'), { target: { value: 'terrain' } })
    await screen.findByRole('alert')
    fireEvent.click(screen.getByRole('button', { name: 'Request observation' }))
    expect(apiClient.submitNow).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Horizon mode')).toHaveValue('terrain')
  })
  it.each([
    'TERRAIN_UNAVAILABLE',
    'JOB_EXPIRED',
    'JOB_NOT_FOUND',
    'NETWORK_ERROR',
  ])('shows %s without a successful fallback', async (code) => {
    vi.mocked(apiClient.submitNow).mockRejectedValue(
      new ApiClientError({ code, message: 'Controlled test failure' }),
    )
    render(<App />)
    await selectCatalog()
    fireEvent.click(screen.getByRole('button', { name: 'Request observation' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(code)
    expect(
      screen.getByText('Simultaneous availability: Unknown'),
    ).toBeInTheDocument()
    expect(apiClient.getResult).not.toHaveBeenCalled()
  })
  it('allows custom entry after catalog failure and offers a catalog retry', async () => {
    vi.mocked(apiClient.getSites)
      .mockRejectedValueOnce(
        new ApiClientError({
          code: 'DATABASE_UNAVAILABLE',
          message: 'Catalog unavailable',
        }),
      )
      .mockResolvedValueOnce(catalog)
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Catalog unavailable',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Retry catalog' }))
    await screen.findByRole('option', { name: 'Synthetic catalog site' })
    fireEvent.click(screen.getByLabelText('Custom coordinates'))
    expect(screen.getByLabelText('Latitude (°)')).toBeInTheDocument()
  })
  it('preserves observation results and visual state when CSA resources fail independently', async () => {
    vi.mocked(apiClient.getResources).mockRejectedValue(
      new ApiClientError({
        code: 'CSA_UNAVAILABLE',
        message: 'CSA feed unavailable',
      }),
    )
    render(<App />)
    await selectCatalog()
    vi.useFakeTimers()
    await act(async () => {
      fireEvent.click(
        screen.getByRole('button', { name: 'Request observation' }),
      )
    })
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    // Observation succeeds and renders despite CSA failure
    expect(screen.getByText('Observation ready')).toBeInTheDocument()
    expect(
      screen.getByText('Synthetic development site'),
    ).toBeInTheDocument()
    expect(screen.getByText('CSA feed unavailable')).toBeInTheDocument()
    expect(visual.map).toHaveBeenCalled()
    expect(visual.scene).toHaveBeenCalled()
  })
})
