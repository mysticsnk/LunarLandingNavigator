import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { timelineResult } from '../../test/fixtures'
import { useTimelinePlayback } from './useTimelinePlayback'

describe('timeline sample playback', () => {
  afterEach(() => {
    cleanup()
    vi.useRealTimers()
  })

  it('navigates only returned samples and stops at the final sample', async () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useTimelinePlayback(timelineResult))
    act(() => result.current.select(2))
    expect(result.current.activeIndex).toBe(2)
    act(() => result.current.play())
    expect(result.current.playing).toBe(true)
    await act(async () => vi.advanceTimersByTimeAsync(1000))
    expect(result.current.activeIndex).toBe(3)
    expect(result.current.playing).toBe(false)
    act(() => result.current.next())
    expect(result.current.activeIndex).toBe(3)
  })

  it('pauses on manual selection and resets selection for a replacement result', () => {
    vi.useFakeTimers()
    const { result, rerender } = renderHook(
      ({ data }) => useTimelinePlayback(data),
      { initialProps: { data: timelineResult } },
    )
    act(() => result.current.play())
    act(() => result.current.select(1))
    expect(result.current.playing).toBe(false)
    expect(result.current.activeIndex).toBe(1)
    rerender({ data: { ...timelineResult } })
    expect(result.current.activeIndex).toBe(0)
  })
})
