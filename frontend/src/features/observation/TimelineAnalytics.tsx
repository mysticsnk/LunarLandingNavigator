import { useState } from 'react'
import type { TimelineResult, TimelineWindow } from '../../api/types'
import { useTimelinePlayback } from './useTimelinePlayback'

type Playback = ReturnType<typeof useTimelinePlayback>

function pointX(timestamp: string, start: number, span: number): number {
  return 56 + ((Date.parse(timestamp) - start) / span) * 884
}

function pointY(elevation: number): number {
  return 18 + ((90 - elevation) / 180) * 220
}

function durationLabel(hours: number): string {
  const wholeMinutes = Math.round(hours * 60)
  const days = Math.floor(wholeMinutes / 1440)
  const remainingHours = Math.floor((wholeMinutes % 1440) / 60)
  const minutes = wholeMinutes % 60
  return [days ? `${days}d` : '', `${remainingHours}h`, minutes ? `${minutes}m` : '']
    .filter(Boolean)
    .join(' ')
}

function WindowList({
  label,
  windows,
  result,
}: {
  label: string
  windows: TimelineWindow[]
  result: TimelineResult
}) {
  return (
    <section className="timeline-window-group" aria-label={label}>
      <h3>{label}</h3>
      {windows.length === 0 ? (
        <p className="muted">No intervals in this computed period.</p>
      ) : (
        <ol className="timeline-window-list">
          {windows.map((window, index) => {
            const atStart = window.start_time === result.start_time
            const atEnd = window.end_time === result.end_time
            return (
              <li key={`${window.start_time}-${window.end_time}`}>
                <span>Window {index + 1}</span>
                <time dateTime={window.start_time}>{window.start_time}</time>
                <span aria-hidden="true">→</span>
                <time dateTime={window.end_time}>{window.end_time}</time>
                <strong>{durationLabel(window.duration_hours)}</strong>
                {atStart && <small>Starts at period boundary</small>}
                {atEnd && <small>Continues through period end (clipped)</small>}
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
}

export function TimelineAnalytics({
  result,
  playback,
}: {
  result: TimelineResult
  playback: Playback
}) {
  const [activePanel, setActivePanel] = useState<'timeline' | 'elevation' | 'windows'>('timeline')
  const points = result.points
  if (points.length === 0)
    return (
      <section className="workspace-card" aria-label="Timeline result">
        <p role="status">The timeline contains no returned samples.</p>
      </section>
    )

  const start = Date.parse(result.start_time)
  const span = Date.parse(result.end_time) - start
  const currentIndex = Math.min(playback.activeIndex, points.length - 1)
  const selected = points[currentIndex]
  const sunPath = points
    .map(
      (point, index) =>
        `${index === 0 ? 'M' : 'L'} ${pointX(point.timestamp, start, span)} ${pointY(point.sun.elevation_deg)}`,
    )
    .join(' ')
  const earthPath = points
    .map(
      (point, index) =>
        `${index === 0 ? 'M' : 'L'} ${pointX(point.timestamp, start, span)} ${pointY(point.earth.elevation_deg)}`,
    )
    .join(' ')
  const tickIndices = [...new Set([0, ...[1, 2, 3].map((n) => Math.round((points.length - 1) * n / 4)), points.length - 1])]
  const selectedX = pointX(selected.timestamp, start, span)

  function selectNearestSample(event: React.MouseEvent<SVGSVGElement>) {
    const bounds = event.currentTarget.getBoundingClientRect()
    if (bounds.width === 0) return
    const svgX = ((event.clientX - bounds.left) / bounds.width) * 960
    const targetTime = start + ((svgX - 56) / 884) * span
    const index = points.reduce(
      (nearest, point, candidate) =>
        Math.abs(Date.parse(point.timestamp) - targetTime) <
        Math.abs(Date.parse(points[nearest].timestamp) - targetTime)
          ? candidate
          : nearest,
      0,
    )
    playback.select(index)
  }

  return (
    <section className="workspace-card timeline-analytics" aria-label="Timeline result">
      <div className="card-heading">
        <div>
          <p className="eyebrow">GEOMETRIC TIMELINE</p>
          <h2>Period analysis</h2>
        </div>
        <span className={`data-badge ${result.meta.data_status}`}>
          {result.meta.data_status}
        </span>
      </div>
      <p className="muted">
        {result.site.name} · {result.start_time} to {result.end_time} (UTC)
      </p>
      <p className="timeline-resolution">
        {result.total_samples} returned samples · {result.meta.time_resolution_minutes}-minute resolution · geometric horizon
      </p>
      <details>
        <summary>Result provenance</summary>
        <dl className="timeline-metrics">
          <dt>Calculation model</dt><dd>{result.meta.model_version}</dd>
          <dt>Generated at</dt><dd><time dateTime={result.meta.generated_at}>{result.meta.generated_at}</time></dd>
          {result.meta.sources.map((source) => (
            <div key={`${source.name}-${source.fetched_at}`}>
              <dt>{source.name}{source.version ? ` · ${source.version}` : ''}</dt>
              <dd><time dateTime={source.fetched_at}>{source.fetched_at}</time> · {source.url}</dd>
            </div>
          ))}
        </dl>
      </details>

      <div className="timeline-tabs" role="tablist" aria-label="Timeline panels">
        {([['timeline', 'Timeline'], ['elevation', 'Elevation plot'], ['windows', 'Golden windows']] as const).map(([id, label]) => (
          <button key={id} type="button" role="tab" aria-selected={activePanel === id} onClick={() => setActivePanel(id)}>{label}</button>
        ))}
      </div>

      {activePanel === 'elevation' && <div role="tabpanel" aria-label="Elevation plot">
      <div className="timeline-chart-legend" aria-label="Chart legend">
        <span><i className="sun-line" /> Sun elevation</span>
        <span><i className="earth-line" /> Earth elevation</span>
        <span><i className="golden-band" /> API golden windows</span>
        <span>Dashed line: geometric horizon (0°)</span>
      </div>
      <svg
        className="timeline-chart"
        viewBox="0 0 960 280"
        role="img"
        aria-label="Sun and Earth elevation at returned UTC timestamps. Click to select the nearest sample."
        onClick={selectNearestSample}
      >
        {[90, 45, 0, -45, -90].map((elevation) => (
          <g key={elevation}>
            <line
              x1="56"
              x2="940"
              y1={pointY(elevation)}
              y2={pointY(elevation)}
              className={elevation === 0 ? 'timeline-horizon' : 'timeline-gridline'}
            />
            <text x="48" y={pointY(elevation) + 4} textAnchor="end" className="chart-axis-label">
              {elevation}°
            </text>
          </g>
        ))}
        {result.golden_windows.map((window) => {
          const x1 = pointX(window.start_time, start, span)
          const x2 = pointX(window.end_time, start, span)
          return (
            <rect
              key={`${window.start_time}-${window.end_time}`}
              x={x1}
              y="18"
              width={Math.max(1, x2 - x1)}
              height="220"
              className="golden-window-band"
            />
          )
        })}
        <path d={sunPath} className="sun-elevation-line" />
        <path d={earthPath} className="earth-elevation-line" />
        <line x1={selectedX} x2={selectedX} y1="18" y2="238" className="timeline-cursor" />
        <circle cx={selectedX} cy={pointY(selected.sun.elevation_deg)} r="4" className="sun-cursor" />
        <circle cx={selectedX} cy={pointY(selected.earth.elevation_deg)} r="4" className="earth-cursor" />
        {tickIndices.map((index) => {
          const timestamp = points[index].timestamp
          return (
            <g key={timestamp}>
              <line x1={pointX(timestamp, start, span)} x2={pointX(timestamp, start, span)} y1="238" y2="243" className="timeline-gridline" />
              <text x={pointX(timestamp, start, span)} y="260" textAnchor="middle" className="chart-axis-label">
                {timestamp.slice(5, 16).replace('T', ' ')}Z
              </text>
            </g>
          )
        })}
      </svg>
      </div>}

      {activePanel === 'timeline' && <div role="tabpanel" aria-label="Timeline">
      <div className="timeline-playback" aria-label="Timeline sample navigation">
        <button type="button" className="secondary-button" onClick={playback.previous} disabled={currentIndex === 0}>
          Previous sample
        </button>
        {playback.playing ? (
          <button type="button" className="secondary-button" onClick={playback.pause}>Pause</button>
        ) : (
          <button type="button" className="secondary-button" onClick={playback.play} disabled={points.length < 2 || currentIndex === points.length - 1}>Play</button>
        )}
        <button type="button" className="secondary-button" onClick={playback.next} disabled={currentIndex >= points.length - 1}>
          Next sample
        </button>
        <label className="field timeline-speed">
          Playback speed
          <select value={playback.speed} onChange={(event) => playback.setSpeed(Number(event.target.value))}>
            {[1, 2, 4].map((speed) => <option key={speed} value={speed}>{speed}×</option>)}
          </select>
        </label>
        <span className="timeline-selected-time">
          <time dateTime={selected.timestamp}>{selected.timestamp} (UTC)</time>
          {' · Δt '}{durationLabel((Date.parse(selected.timestamp) - start) / 3_600_000)}
        </span>
        <label className="field timeline-slider">
          Sample {currentIndex + 1} of {points.length}
          <input
            type="range"
            min="0"
            max={points.length - 1}
            step="1"
            value={currentIndex}
            onChange={(event) => playback.select(Number(event.target.value))}
            aria-label="Selected timeline sample"
          />
        </label>
      </div>
      <p className="field-help">Playback advances through returned samples only. It pauses at the last sample; no values are interpolated.</p>

      <h3>Selected sample values</h3>
      <p className="muted">{selected.timestamp} (UTC) · {result.step_minutes}-minute sample resolution</p>
      <div className="table-scroll">
        <table className="observation-table">
          <caption>Values returned for the selected sample</caption>
          <thead><tr><th>Body</th><th>Azimuth</th><th>Elevation</th><th>Horizon</th><th>Visible</th></tr></thead>
          <tbody>
            {(['sun', 'earth'] as const).map((body) => (
              <tr key={body}>
                <th scope="row">{body === 'sun' ? 'Sun' : 'Earth'}</th>
                <td>{selected[body].azimuth_deg}°</td>
                <td>{selected[body].elevation_deg}°</td>
                <td>{selected[body].horizon_elevation_deg}°</td>
                <td>{selected[body].visible ? 'Visible' : 'Not visible'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="availability">Simultaneous golden state: <strong>{selected.is_golden_window ? 'Yes' : 'No'}</strong></p>

      <h3>Summary from the API</h3>
      <dl className="timeline-metrics">
        <dt>Sunlight</dt><dd>{result.summary.sunlit_hours} h ({result.summary.sunlit_pct}%)</dd>
        <dt>Earth visibility</dt><dd>{result.summary.earth_visible_hours} h ({result.summary.earth_visible_pct}%)</dd>
        <dt>Golden windows total</dt><dd>{result.summary.golden_hours} h ({result.summary.golden_pct}%)</dd>
        <dt>Longest continuous golden window</dt><dd>{result.summary.longest_golden_window_hours} h</dd>
        <dt>Average Sun elevation</dt><dd>{result.summary.average_sun_elevation_deg}°</dd>
        <dt>Next observed sunset</dt><dd>{result.summary.next_sunset_at ?? 'No set event observed in this computed period.'}</dd>
        <dt>Next observed Earthset</dt><dd>{result.summary.next_earthset_at ?? 'No set event observed in this computed period.'}</dd>
      </dl>
      </div>}
      {activePanel === 'windows' && <div role="tabpanel" aria-label="Golden windows">
      <div className="timeline-window-groups">
        <WindowList label="Sunlight intervals" windows={result.sunlight_windows} result={result} />
        <WindowList label="Earth visibility intervals" windows={result.earth_visibility_windows} result={result} />
        <WindowList label="Golden windows" windows={result.golden_windows} result={result} />
      </div>
      <p className="field-help">Set events are observed sample transitions. A period-clipped interval does not establish a physical sunset or Earthset.</p>
      </div>}
    </section>
  )
}
