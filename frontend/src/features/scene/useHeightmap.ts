import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient } from '../../api/client'
import type { Heightmap } from '../../api/types'

// Memory cache for fetched heightmaps by regionId to avoid repeated network calls
const heightmapCache = new Map<string, Heightmap>()

export function clearHeightmapCache(): void {
  heightmapCache.clear()
}

export function useHeightmap(regionId?: string | null) {
  const [prevRegionId, setPrevRegionId] = useState<string | null>(regionId ?? null)
  const [heightmap, setHeightmap] = useState<Heightmap | null>(() => {
    if (regionId && heightmapCache.has(regionId)) {
      return heightmapCache.get(regionId)!
    }
    return null
  })
  const [loading, setLoading] = useState<boolean>(() => Boolean(regionId && !heightmapCache.has(regionId)))
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  const activeRegionRef = useRef<string | null>(regionId ?? null)

  const currentRegion = regionId ?? null
  if (currentRegion !== prevRegionId) {
    setPrevRegionId(currentRegion)
    const cached = currentRegion && heightmapCache.has(currentRegion) ? heightmapCache.get(currentRegion)! : null
    setHeightmap(cached)
    setLoading(Boolean(currentRegion && !cached))
    setError(null)
  }

  const retry = useCallback(() => {
    if (regionId) {
      heightmapCache.delete(regionId)
      setAttempt((prev) => prev + 1)
      setHeightmap(null)
      setLoading(true)
      setError(null)
    }
  }, [regionId])

  useEffect(() => {
    activeRegionRef.current = regionId ?? null

    if (!regionId || heightmapCache.has(regionId)) {
      return
    }

    const controller = new AbortController()

    apiClient
      .getHeightmap(regionId, { signal: controller.signal })
      .then((data) => {
        if (activeRegionRef.current === regionId) {
          heightmapCache.set(regionId, data)
          setHeightmap(data)
          setLoading(false)
          setError(null)
        }
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        if (activeRegionRef.current === regionId) {
          setHeightmap(null)
          setLoading(false)
          const message = err instanceof Error ? err.message : 'Failed to load terrain heightmap'
          setError(message)
        }
      })

    return () => {
      controller.abort()
    }
  }, [regionId, attempt])

  return {
    heightmap,
    loading,
    error,
    retry,
  }
}
