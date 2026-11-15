import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '../../api/client'
import { ApiClientError } from '../../api/errors'
import { deferred, comparisonAccepted, comparisonRequest, comparisonResult, comparisonSucceeded } from '../../test/fixtures'
import type { JobAccepted } from '../../api/types'
import { useComparison } from './useComparison'

describe('comparison job lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.spyOn(apiClient, 'submitComparison').mockResolvedValue(comparisonAccepted)
    vi.spyOn(apiClient, 'getJob').mockResolvedValue(comparisonSucceeded)
    vi.spyOn(apiClient, 'getComparisonResult').mockResolvedValue(comparisonResult)
  })
  afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks() })

  it('polls the accepted comparison job and loads the complete result', async () => {
    const { result } = renderHook(useComparison)
    await act(async () => result.current.submit(comparisonRequest))
    expect(result.current.phase).toBe('queued')
    await act(async () => vi.advanceTimersByTimeAsync(2000))
    expect(result.current.phase).toBe('succeeded')
    expect(result.current.result).toEqual(comparisonResult)
    expect(apiClient.submitComparison).toHaveBeenCalledWith(comparisonRequest, expect.any(Object))
  })

  it('does not fetch a result or display a partial ranking after job failure', async () => {
    vi.mocked(apiClient.getJob).mockResolvedValueOnce({ ...comparisonSucceeded, status: 'failed', error: { code: 'PROVIDER_UNAVAILABLE', message: 'Unavailable', details: [], request_id: 'comparison-test' } })
    const { result } = renderHook(useComparison)
    await act(async () => result.current.submit(comparisonRequest))
    await act(async () => vi.advanceTimersByTimeAsync(2000))
    expect(result.current.phase).toBe('failed')
    expect(result.current.result).toBeNull()
    expect(apiClient.getComparisonResult).not.toHaveBeenCalled()
  })

  it('does not let an older accepted job replace the newer comparison', async () => {
    const late = deferred<JobAccepted>()
    vi.mocked(apiClient.submitComparison).mockReturnValueOnce(late.promise)
    const { result } = renderHook(useComparison)
    act(() => { void result.current.submit(comparisonRequest) })
    await act(async () => result.current.submit({ ...comparisonRequest, observer_height_m: 3 }))
    await act(async () => vi.advanceTimersByTimeAsync(2000))
    await act(async () => late.resolve(comparisonAccepted))
    expect(result.current.phase).toBe('succeeded')
    expect(result.current.request?.observer_height_m).toBe(3)
    expect(result.current.result).toEqual(comparisonResult)
    expect(apiClient.getJob).toHaveBeenCalledTimes(1)
  })

  it('reports an expired job without displaying a ranking', async () => {
    vi.mocked(apiClient.getJob).mockRejectedValueOnce(new ApiClientError({ code: 'JOB_EXPIRED', message: 'Comparison job expired.' }))
    const { result } = renderHook(useComparison)
    await act(async () => result.current.submit(comparisonRequest))
    await act(async () => vi.advanceTimersByTimeAsync(2000))
    expect(result.current.phase).toBe('error')
    expect(result.current.result).toBeNull()
    expect(result.current.error?.code).toBe('JOB_EXPIRED')
    expect(apiClient.getComparisonResult).not.toHaveBeenCalled()
  })
})
