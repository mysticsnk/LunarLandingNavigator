import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { timelineResult } from '../../test/fixtures'
import { TimelineAnalytics } from './TimelineAnalytics'

describe('TimelineAnalytics panels', () => {
  it('switches between returned timeline values, elevation plot, and API intervals', () => {
    render(<TimelineAnalytics result={timelineResult} playback={{
      activeIndex: 0,
      playing: false,
      speed: 1,
      select: vi.fn(),
      play: vi.fn(),
      pause: vi.fn(),
      setSpeed: vi.fn(),
      previous: vi.fn(),
      next: vi.fn(),
    }} />)

    expect(screen.getByRole('tabpanel', { name: 'Timeline' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Elevation plot' }))
    expect(screen.getByRole('img', { name: /Sun and Earth elevation at returned UTC timestamps/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Golden windows' }))
    expect(screen.getByRole('tabpanel', { name: 'Golden windows' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Golden windows' })).toBeInTheDocument()
  })
})
