import { useEffect, useState, type FormEvent } from 'react'
import { apiClient } from '../../api/client'
import { ApiClientError } from '../../api/errors'
import type { Site, SiteList, LayerList } from '../../api/types'
import { SourceLink } from '../../components/SourceLink'
import { RequestError } from '../../components/RequestError'
import { LunarMap } from '../map'
import { LunarScene } from '../scene'
import {
  buildRequest,
  buildTimelineRequest,
  initialScenario,
  type ScenarioDraft,
} from './scenario'
import { useObservation } from './useObservation'
import { useTimeline } from './useTimeline'
import { useTimelinePlayback } from './useTimelinePlayback'
import { TimelineAnalytics } from './TimelineAnalytics'
import { ObservationResult } from './ObservationResult'
import { CSAResources } from '../resources/CSAResources'
import { HealthCard } from '../health/HealthCard'

const phases = {
  idle: 'No observation requested',
  submitting: 'Submitting observation…',
  queued: 'Queued — waiting for the worker',
  running: 'Running — retrieving the observation',
  'loading-result': 'Loading observation result…',
  succeeded: 'Observation ready',
  failed: 'Observation failed',
  error: 'Request could not be completed',
}

export function ObservationWorkspace() {
  const [draft, setDraft] = useState(initialScenario)
  const [workflow, setWorkflow] = useState<'now' | 'timeline'>('now')
  const [category, setCategory] = useState<Site['category'] | ''>('')
  const [offset, setOffset] = useState(0)
  const [catalog, setCatalog] = useState<SiteList | null>(null)
  const [catalogError, setCatalogError] = useState<ApiClientError | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [validation, setValidation] = useState<string | null>(null)
  const observation = useObservation()
  const timeline = useTimeline()
  const playback = useTimelinePlayback(timeline.result)

  useEffect(() => {
    const controller = new AbortController()
    apiClient
      .getSites(
        { ...(category ? { category } : {}), limit: 50, offset },
        { signal: controller.signal },
      )
      .then((value) => {
        if (!controller.signal.aborted) setCatalog(value)
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setCatalogError(
            error instanceof ApiClientError
              ? error
              : new ApiClientError({
                  message: 'Unable to load the site catalog.',
                }),
          )
      })
    return () => controller.abort()
  }, [category, offset, attempt])

  const [mapLayers, setMapLayers] = useState<LayerList | null>(null)
  const [mapError, setMapError] = useState<ApiClientError | null>(null)
  const [mapAttempt, setMapAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    apiClient
      .getMapLayers({ signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) setMapLayers(value)
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setMapError(
            error instanceof ApiClientError
              ? error
              : new ApiClientError({ message: 'Unable to load map layers.' }),
          )
      })
    return () => controller.abort()
  }, [mapAttempt])

  function reloadCatalog(nextCategory = category, nextOffset = offset) {
    setCatalog(null)
    setCatalogError(null)
    setCategory(nextCategory)
    setOffset(nextOffset)
    setAttempt((value) => value + 1)
  }

  function change(patch: Partial<ScenarioDraft>) {
    observation.reset()
    timeline.reset()
    setValidation(null)
    setDraft((previous) => ({ ...previous, ...patch }))
  }

  function selectWorkflow(next: 'now' | 'timeline') {
    observation.reset()
    timeline.reset()
    setValidation(null)
    setWorkflow(next)
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    try {
      setValidation(null)
      if (workflow === 'timeline')
        void timeline.submit(buildTimelineRequest(draft))
      else void observation.submit(buildRequest(draft))
    } catch (error) {
      observation.reset()
      timeline.reset()
      setValidation((error as Error).message)
    }
  }

  const result = observation.result
  const timelineResult = timeline.result
  const selectedPoint =
    workflow === 'timeline'
      ? timelineResult?.points[playback.activeIndex] ?? null
      : result?.point ?? null
  const activeJob = workflow === 'timeline' ? timeline : observation
  const busy = activeJob.busy
  const latitude = Number(draft.latitude)
  const longitude = Number(draft.longitude)
  // The map owns coordinate transformations; wait for server normalization outside its accepted longitude range.
  const displayedSite = workflow === 'timeline' ? timelineResult?.site : result?.site
  const coordinate = displayedSite
    ? { latitude: displayedSite.latitude, longitude: displayedSite.longitude }
    : draft.mode === 'catalog'
      ? draft.site
      : draft.latitude.trim() &&
          draft.longitude.trim() &&
          Number.isFinite(latitude) &&
          Number.isFinite(longitude) &&
          latitude >= -90 &&
          latitude <= 90 &&
          longitude >= -180 &&
          longitude < 180
        ? { latitude, longitude }
        : null

  return (
    <main className="app-main">
      <div className="workspace-intro">
        <p className="eyebrow">{workflow === 'timeline' ? 'MULTI-DAY TIMELINE' : 'SINGLE-TIME OBSERVATION'}</p>
        <h2>Explore a lunar vantage point</h2>
        <p className="muted">
          Choose a location and a UTC {workflow === 'timeline' ? 'period' : 'instant'} to inspect geometric Sun and Earth visibility.
        </p>
      </div>
      <div className="main-grid">
        <aside className="grid-sidebar">
          <section
            className="workspace-card"
            aria-labelledby="scenario-heading"
          >
            <h2 id="scenario-heading">Observation setup</h2>
            <form onSubmit={submit} noValidate>
              <fieldset>
                <legend>Analysis</legend>
                <div className="mode-switch">
                  <label>
                    <input
                      type="radio"
                      name="analysis-mode"
                      checked={workflow === 'now'}
                      onChange={() => selectWorkflow('now')}
                    />{' '}
                    Single instant
                  </label>
                  <label>
                    <input
                      type="radio"
                      name="analysis-mode"
                      checked={workflow === 'timeline'}
                      onChange={() => selectWorkflow('timeline')}
                    />{' '}
                    Timeline
                  </label>
                </div>
              </fieldset>
              <fieldset>
                <legend>Location</legend>
                <div className="mode-switch">
                  <label>
                    <input
                      type="radio"
                      name="site-mode"
                      checked={draft.mode === 'catalog'}
                      onChange={() => change({ mode: 'catalog' })}
                    />{' '}
                    Catalog
                  </label>
                  <label>
                    <input
                      type="radio"
                      name="site-mode"
                      checked={draft.mode === 'custom'}
                      onChange={() => change({ mode: 'custom' })}
                    />{' '}
                    Custom coordinates
                  </label>
                </div>
                {draft.mode === 'catalog' ? (
                  <>
                    <label className="field">
                      Category
                      <select
                        value={category}
                        onChange={(event) => {
                          reloadCatalog(
                            event.target.value as typeof category,
                            0,
                          )
                          change({ site: null })
                        }}
                      >
                        <option value="">All categories</option>
                        {['artemis', 'apollo', 'clps', 'international'].map(
                          (value) => (
                            <option key={value} value={value}>
                              {value.toUpperCase()}
                            </option>
                          ),
                        )}
                      </select>
                    </label>
                    {!catalog && !catalogError && (
                      <p role="status">Loading site catalog…</p>
                    )}
                    {catalogError && (
                      <>
                        <RequestError error={catalogError} />
                        <button
                          type="button"
                          className="secondary-button"
                          onClick={() => reloadCatalog()}
                        >
                          Retry catalog
                        </button>
                      </>
                    )}
                    <label className="field">
                      Catalog site
                      <select
                        value={draft.site?.id ?? ''}
                        disabled={!catalog}
                        onChange={(event) =>
                          change({
                            site:
                              catalog?.items.find(
                                (site) => site.id === event.target.value,
                              ) ?? null,
                          })
                        }
                      >
                        <option value="">Choose a site</option>
                        {draft.site &&
                          !catalog?.items.some(
                            (site) => site.id === draft.site?.id,
                          ) && (
                            <option value={draft.site.id}>
                              {draft.site.name}
                            </option>
                          )}
                        {catalog?.items.map((site) => (
                          <option key={site.id} value={site.id}>
                            {site.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    {catalog && (
                      <div className="pagination">
                        <small>
                          {catalog.total === 0
                            ? 'No matching sites'
                            : `${catalog.offset + 1}–${Math.min(catalog.offset + catalog.limit, catalog.total)} of ${catalog.total} sites`}
                        </small>
                        <button
                          type="button"
                          aria-label="Previous sites"
                          disabled={offset === 0}
                          onClick={() =>
                            reloadCatalog(category, Math.max(0, offset - 50))
                          }
                        >
                          ←
                        </button>
                        <button
                          type="button"
                          aria-label="Next sites"
                          disabled={offset + catalog.limit >= catalog.total}
                          onClick={() => reloadCatalog(category, offset + 50)}
                        >
                          →
                        </button>
                      </div>
                    )}
                    {draft.site && (
                      <div className="site-description">
                        <p>{draft.site.description}</p>
                        <p className="muted">
                          {draft.site.latitude}° latitude ·{' '}
                          {draft.site.longitude}° east
                        </p>
                        <div className="source-links">
                          <SourceLink url={draft.site.source_url}>
                            Official site source ↗
                          </SourceLink>
                          {draft.site.quickmap_url && (
                            <SourceLink url={draft.site.quickmap_url}>
                              QuickMap ↗
                            </SourceLink>
                          )}
                        </div>
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    <label className="field">
                      Custom name (optional)
                      <input
                        value={draft.name}
                        onChange={(event) =>
                          change({ name: event.target.value })
                        }
                      />
                    </label>
                    <div className="field-pair">
                      <label className="field">
                        Latitude (°)
                        <input
                          type="number"
                          step="any"
                          min="-90"
                          max="90"
                          value={draft.latitude}
                          onChange={(event) =>
                            change({ latitude: event.target.value })
                          }
                        />
                      </label>
                      <label className="field">
                        Longitude (° east)
                        <input
                          type="number"
                          step="any"
                          min="-180"
                          value={draft.longitude}
                          onChange={(event) =>
                            change({ longitude: event.target.value })
                          }
                        />
                      </label>
                    </div>
                    <p className="field-help">
                      Latitude −90 to 90; longitude −180 to less than 360. The
                      API returns normalized longitude in [−180, 180).
                    </p>
                  </>
                )}
              </fieldset>
              <fieldset>
                <legend>Time & model</legend>
                <label className="field">
                  {workflow === 'timeline' ? 'Period start (UTC)' : 'Observation date and time (UTC)'}
                  <input
                    type="datetime-local"
                    step="1"
                    min="2000-01-01T00:00:00"
                    max="2049-12-31T23:59:59"
                    value={draft.utcTime}
                    onChange={(event) =>
                      change({ utcTime: event.target.value })
                    }
                  />
                </label>
                <p className="field-help">
                  Enter UTC explicitly, regardless of your device time zone. Supported years: 2000–2049; whole seconds.
                </p>
                {workflow === 'timeline' && (
                  <div className="field-pair">
                    <label className="field">
                      Duration (days)
                      <input
                        type="number"
                        min="1"
                        max="30"
                        step="1"
                        value={draft.durationDays}
                        onChange={(event) => change({ durationDays: event.target.value })}
                      />
                    </label>
                    <label className="field">
                      Time step (minutes)
                      <select
                        value={draft.stepMinutes}
                        onChange={(event) => change({ stepMinutes: event.target.value })}
                      >
                        {[15, 30, 60, 120, 180, 360].map((step) => (
                          <option key={step} value={step}>{step}</option>
                        ))}
                      </select>
                    </label>
                  </div>
                )}
                <div className="field-pair">
                  <label className="field">
                    Observer height (m)
                    <input
                      type="number"
                      step="any"
                      min="0"
                      max="20"
                      value={draft.height}
                      onChange={(event) =>
                        change({ height: event.target.value })
                      }
                    />
                  </label>
                  <label className="field">
                    Visibility margin (°)
                    <input
                      type="number"
                      step="any"
                      min="0"
                      max="5"
                      value={draft.margin}
                      onChange={(event) =>
                        change({ margin: event.target.value })
                      }
                    />
                  </label>
                </div>
                <p className="field-help">
                  Geometric horizon · terrain occlusion is unavailable in Stage 3.
                </p>
              </fieldset>
              {validation && (
                <p role="alert" className="request-error">
                  {validation}
                </p>
              )}
              <button className="primary-button" type="submit">
                {busy
                  ? workflow === 'timeline' ? 'Replace with new timeline' : 'Replace with new observation'
                  : workflow === 'timeline' ? 'Request timeline' : 'Request observation'}
              </button>
            </form>
            <div className="job-progress" role="status" aria-live="polite">
              <span
                className={
                  busy ? 'progress-dot active' : 'progress-dot'
                }
              />
              {workflow === 'timeline'
                ? {
                    idle: 'No timeline requested',
                    submitting: 'Submitting timeline…',
                    queued: 'Queued — waiting for the worker',
                    running: 'Running — calculating timeline',
                    'loading-result': 'Loading timeline result…',
                    succeeded: 'Timeline ready',
                    failed: 'Timeline failed',
                    error: 'Timeline request could not be completed',
                  }[timeline.phase]
                : phases[observation.phase]}
            </div>
            {activeJob.jobId && (
              <p className="job-id">Job {activeJob.jobId}</p>
            )}
            {busy && (
              <>
                <p className="field-help">
                  Checking job status every two seconds. Stopping here leaves
                  the server job running.
                </p>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={activeJob.reset}
                >
                  Stop waiting
                </button>
              </>
            )}
            {activeJob.error && <RequestError error={activeJob.error} />}
          </section>
          <details className="health-details-panel">
            <summary>Backend connection</summary>
            <HealthCard />
          </details>
        </aside>
        <div className="grid-content">
          <div className="visual-grid">
            <section
              className="workspace-card visual-card"
              aria-labelledby="map-heading"
            >
              <h2 id="map-heading">Lunar location</h2>
              <p className="muted">
                Lunar imagery; click inside the map to select coordinates.
              </p>
              <div className="map-viewport">
                {!mapLayers && !mapError && (
                  <p role="status">Loading map layers...</p>
                )}
                {mapError && <RequestError error={mapError} />}
                {mapLayers?.items.length === 0 && (
                  <p>No registered map layers are available.</p>
                )}
                {mapError && (
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => {
                      setMapError(null)
                      setMapAttempt((value) => value + 1)
                    }}
                  >
                    Retry map layers
                  </button>
                )}
                {!!mapLayers?.items.length && (
                  <LunarMap
                    layers={mapLayers.items}
                    quickmapUrl={
                      draft.mode === 'catalog' ? draft.site?.quickmap_url : null
                    }
                    selectedCoordinate={coordinate || null}
                    selectedSiteId={
                      draft.mode === 'catalog' ? draft.site?.id : null
                    }
                    onSelectCoordinate={(value) =>
                      change({
                        mode: 'custom',
                        latitude: String(value.latitude),
                        longitude: String(value.longitude),
                      })
                    }
                  />
                )}
              </div>
              <p className="field-help">
                Registered Moon Trek / LROC imagery. Physical terrain is not
                modeled.
              </p>
            </section>
            <section
              className="workspace-card visual-card"
              aria-labelledby="scene-heading"
            >
              <h2 id="scene-heading">Local sky directions</h2>
              <p className="muted">
                Schematic local ENU scene · directions from the observation API.
              </p>
              <div className="scene-viewport">
                <LunarScene
                  observationPoint={selectedPoint}
                  site={
                    (workflow === 'timeline' ? timelineResult?.site : result?.site) ??
                    (draft.mode === 'catalog' ? draft.site : null)
                  }
                  dataStatus={(workflow === 'timeline' ? timelineResult?.meta.data_status : result?.meta.data_status) ?? null}
                  sunDirectionEnu={selectedPoint?.sun.direction_enu ?? null}
                  earthDirectionEnu={selectedPoint?.earth.direction_enu ?? null}
                  observerHeightM={(workflow === 'timeline' ? timelineResult?.site.observer_height_m : result?.site.observer_height_m) ?? undefined}
                  isLoading={busy}
                />
              </div>
              <p className="field-help">
                Marker distances are for display; terrain is not modeled.
              </p>
            </section>
          </div>
          {workflow === 'timeline' ? (
            timelineResult ? (
              <TimelineAnalytics result={timelineResult} playback={playback} />
            ) : (
              <section className="workspace-card" aria-label="Timeline result">
                <h2>Timeline analysis</h2>
                <p className="muted">Submit a period to load returned samples, intervals, and summary metrics.</p>
              </section>
            )
          ) : (
            <ObservationResult result={result} />
          )}
          <CSAResources />
        </div>
      </div>
    </main>
  )
}
