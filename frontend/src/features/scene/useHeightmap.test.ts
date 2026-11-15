import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '../../api/client'
import { ApiClientError } from '../../api/errors'
import { heightmapFixture } from '../../test/fixtures'
import { clearHeightmapCache, useHeightmap } from './useHeightmap'

describe('useHeightmap hook', () => {
  beforeEach(() => {
    clearHeightmapCache()
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('returns null when regionId is null or undefined without making an API call', () => {
    const spy = vi.spyOn(apiClient, 'getHeightmap')
    const { result } = renderHook(() => useHeightmap(null))

    expect(result.current.heightmap).toBeNull()
    expect(result.current.loading).toBe(false)
    expect(result.current.error).toBeNull()
    expect(spy).not.toHaveBeenCalled()
  })

  it('fetches and caches heightmap successfully', async () => {
    const spy = vi
      .spyOn(apiClient, 'getHeightmap')
      .mockResolvedValue(heightmapFixture)

    const { result } = renderHook(() =>
      useHeightmap('shackleton_connecting_ridge'),
    )

    expect(result.current.loading).toBe(true)

    // Wait for resolution
    await act(async () => {
      await Promise.resolve()
    })

    expect(result.current.loading).toBe(false)
    expect(result.current.error).toBeNull()
    expect(result.current.heightmap).toEqual(heightmapFixture)
    expect(spy).toHaveBeenCalledTimes(1)

    // Re-rendering with the same regionId should use cache and not make another API call
    const { result: cachedResult } = renderHook(() =>
      useHeightmap('shackleton_connecting_ridge'),
    )
    expect(cachedResult.current.heightmap).toEqual(heightmapFixture)
    expect(cachedResult.current.loading).toBe(false)
    expect(spy).toHaveBeenCalledTimes(1) // Still 1 call
  })

  it('resets heightmap when regionId changes to avoid showing old terrain for a new site', async () => {
    const heightmapA = { ...heightmapFixture, region_id: 'region_a' }
    const heightmapB = { ...heightmapFixture, region_id: 'region_b' }

    vi.spyOn(apiClient, 'getHeightmap')
      .mockResolvedValueOnce(heightmapA)
      .mockResolvedValueOnce(heightmapB)

    const { result, rerender } = renderHook(
      ({ id }) => useHeightmap(id),
      { initialProps: { id: 'region_a' } },
    )

    await act(async () => {
      await Promise.resolve()
    })
    expect(result.current.heightmap?.region_id).toBe('region_a')

    // Switch region to region_b
    rerender({ id: 'region_b' })

    // Old heightmap is immediately cleared while loading new
    expect(result.current.heightmap).toBeNull()
    expect(result.current.loading).toBe(true)

    await act(async () => {
      await Promise.resolve()
    })
    expect(result.current.heightmap?.region_id).toBe('region_b')
  })

  it('handles API errors gracefully and allows retry', async () => {
    vi.spyOn(apiClient, 'getHeightmap')
      .mockRejectedValueOnce(
        new ApiClientError({
          code: 'TERRAIN_UNAVAILABLE',
          message: 'Terrain DEM unavailable for requested region',
        }),
      )
      .mockResolvedValueOnce(heightmapFixture)

    const { result } = renderHook(() => useHeightmap('shackleton_connecting_ridge'))

    await act(async () => {
      await Promise.resolve()
    })

    expect(result.current.loading).toBe(false)
    expect(result.current.heightmap).toBeNull()
    expect(result.current.error).toBe('Terrain DEM unavailable for requested region')

    // Click retry
    await act(async () => {
      result.current.retry()
    })

    await act(async () => {
      await Promise.resolve()
    })

    expect(result.current.loading).toBe(false)
    expect(result.current.error).toBeNull()
    expect(result.current.heightmap).toEqual(heightmapFixture)
  })
})
