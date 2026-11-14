import { useCallback, useEffect, useState } from 'react'
import type { TimelineResult } from '../../api/types'

interface Selection {
  result: TimelineResult | null
  index: number
}

export function useTimelinePlayback(result: TimelineResult | null) {
  const [selection, setSelection] = useState<Selection>({
    result: null,
    index: 0,
  })
  const [playingResult, setPlayingResult] = useState<TimelineResult | null>(null)
  const playing = playingResult === result && result !== null
  const [speed, setSpeed] = useState(1)
  const activeIndex = selection.result === result ? selection.index : 0
  const lastIndex = Math.max(0, (result?.points.length ?? 0) - 1)

  const select = useCallback(
    (index: number) => {
      setPlayingResult(null)
      setSelection({
        result,
        index: Math.max(0, Math.min(lastIndex, Math.round(index))),
      })
    },
    [lastIndex, result],
  )

  const play = useCallback(() => {
    if (!result || result.points.length < 2 || activeIndex >= lastIndex) {
      setPlayingResult(null)
      return
    }
    setPlayingResult(result)
  }, [activeIndex, lastIndex, result])

  useEffect(() => {
    if (!playing || !result || activeIndex >= lastIndex) {
      return
    }
    const timeout = setTimeout(() => {
      const nextIndex = activeIndex + 1
      setSelection({ result, index: nextIndex })
      if (nextIndex >= lastIndex) setPlayingResult(null)
    }, 1000 / speed)
    return () => clearTimeout(timeout)
  }, [activeIndex, lastIndex, playing, result, speed])

  return {
    activeIndex,
    playing,
    speed,
    select,
    play,
    pause: () => setPlayingResult(null),
    setSpeed,
    previous: () => select(activeIndex - 1),
    next: () => select(activeIndex + 1),
  }
}
