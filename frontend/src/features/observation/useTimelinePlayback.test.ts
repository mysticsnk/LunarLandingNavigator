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

  it('supports previous navigation and multiple playback speeds', async () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useTimelinePlayback(timelineResult))
    act(() => result.current.select(2))
    act(() => result.current.previous())
    expect(result.current.activeIndex).toBe(1)

    // Speed 2x: advances every 500ms
    act(() => result.current.setSpeed(2))
    act(() => result.current.play())
    expect(result.current.playing).toBe(true)
    await act(async () => vi.advanceTimersByTimeAsync(500))
    expect(result.current.activeIndex).toBe(2)
    await act(async () => vi.advanceTimersByTimeAsync(500))
    expect(result.current.activeIndex).toBe(3)
    expect(result.current.playing).toBe(false)
  })

  it('defensively handles null, empty, or single-point timelines', () => {
    const { result: nullResult } = renderHook(() => useTimelinePlayback(null))
    expect(nullResult.current.activeIndex).toBe(0)
    act(() => nullResult.current.play())
    expect(nullResult.current.playing).toBe(false)

    const singlePointResult = { ...timelineResult, points: [timelineResult.points[0]] }
    const { result: singleResult } = renderHook(() => useTimelinePlayback(singlePointResult))
    expect(singleResult.current.activeIndex).toBe(0)
    act(() => singleResult.current.play())
    expect(singleResult.current.playing).toBe(false)
  })

  it('clamps manual selection to valid sample range [0, lastIndex]', () => {
    const { result } = renderHook(() => useTimelinePlayback(timelineResult))
    act(() => result.current.select(-5))
    expect(result.current.activeIndex).toBe(0)
    act(() => result.current.select(999))
    expect(result.current.activeIndex).toBe(timelineResult.points.length - 1)
  })
})
