import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '../../api/client'
import { ApiClientError } from '../../api/errors'
import { deferred, timelineAccepted, timelineResult } from '../../test/fixtures'
import type { Job, JobAccepted } from '../../api/types'
import { useTimeline } from './useTimeline'

const request = {
  site: { site_id: 'development-site' },
  start_time: '2027-07-15T00:00:00Z',
  duration_days: 1,
  step_minutes: 360 as const,
  horizon_mode: 'geometric' as const,
  observer_height_m: 2,
  visibility_margin_deg: 0,
}

describe('timeline job lifecycle', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.spyOn(apiClient, 'submitTimeline').mockResolvedValue(timelineAccepted)
    vi.spyOn(apiClient, 'getJob').mockResolvedValue({
      job_id: timelineAccepted.job_id,
      kind: 'timeline',
      status: 'succeeded',
      created_at: '2027-07-15T00:00:00Z',
      started_at: '2027-07-15T00:00:01Z',
      finished_at: '2027-07-15T00:00:02Z',
      result_url: timelineAccepted.result_url,
      error: null,
    })
    vi.spyOn(apiClient, 'getTimelineResult').mockResolvedValue(timelineResult)
  })

  afterEach(() => {
    cleanup()
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('polls the timeline job and fetches its result after success', async () => {
    const { result } = renderHook(useTimeline)
    await act(async () => result.current.submit(request))
    expect(result.current.phase).toBe('queued')
    await act(async () => vi.advanceTimersByTimeAsync(2000))
    expect(result.current.phase).toBe('succeeded')
    expect(result.current.result).toEqual(timelineResult)
    expect(apiClient.submitTimeline).toHaveBeenCalledWith(request, expect.any(Object))
    expect(apiClient.getJob).toHaveBeenCalledWith(timelineAccepted.status_url, expect.any(Object))
    expect(apiClient.getTimelineResult).toHaveBeenCalledWith(timelineAccepted.result_url, expect.any(Object))
  })

  it('preserves a structured provider failure and does not fetch a result', async () => {
    vi.mocked(apiClient.getJob).mockResolvedValueOnce({
      job_id: timelineAccepted.job_id,
      kind: 'timeline',
      status: 'failed',
      created_at: '2027-07-15T00:00:00Z',
      started_at: '2027-07-15T00:00:01Z',
      finished_at: '2027-07-15T00:00:02Z',
      result_url: timelineAccepted.result_url,
      error: {
        code: 'PROVIDER_UNAVAILABLE',
        message: 'Horizons is unavailable',
        details: [],
        request_id: 'timeline-test-request',
      },
    })
    const { result } = renderHook(useTimeline)
    await act(async () => result.current.submit(request))
    await act(async () => vi.advanceTimersByTimeAsync(2000))
    expect(result.current.phase).toBe('failed')
    expect(result.current.error).toMatchObject({ code: 'PROVIDER_UNAVAILABLE' })
    expect(apiClient.getTimelineResult).not.toHaveBeenCalled()
  })

  it('ignores a late accepted response after the request is replaced', async () => {
    const late = deferred<JobAccepted>()
    vi.mocked(apiClient.submitTimeline).mockReturnValueOnce(late.promise)
    const { result } = renderHook(useTimeline)
    act(() => void result.current.submit(request))
    await act(async () => result.current.submit({ ...request, start_time: '2028-01-01T00:00:00Z' }))
    await act(async () => {
      late.resolve({ ...timelineAccepted, job_id: 'late-timeline-job' })
      await late.promise
    })
    expect(result.current.jobId).toBe(timelineAccepted.job_id)
    await act(async () => vi.advanceTimersByTimeAsync(2000))
    expect(result.current.result).toEqual(timelineResult)
    expect(apiClient.getJob).toHaveBeenCalledTimes(1)
  })

  it('aborts polling when waiting is stopped', async () => {
    const pending = deferred<Job>()
    vi.mocked(apiClient.getJob).mockReturnValue(pending.promise)
    const { result } = renderHook(useTimeline)
    await act(async () => result.current.submit(request))
    await act(async () => vi.advanceTimersByTimeAsync(2000))
    const statusSignal = vi.mocked(apiClient.getJob).mock.calls[0][1]!.signal!
    act(() => result.current.reset())
    expect(statusSignal.aborted).toBe(true)
    await act(async () => {
      pending.reject(new ApiClientError({ code: 'REQUEST_ABORTED', message: 'Aborted' }))
      await pending.promise.catch(() => undefined)
    })
    expect(result.current.phase).toBe('idle')
    expect(apiClient.getTimelineResult).not.toHaveBeenCalled()
  })
})
