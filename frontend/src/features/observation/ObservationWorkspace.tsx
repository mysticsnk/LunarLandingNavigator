import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { apiClient } from '../../api/client'
import { ApiClientError } from '../../api/errors'
import type { Site, SiteList, LayerList, TerrainCoverage } from '../../api/types'
import { SourceLink } from '../../components/SourceLink'
import { RequestError } from '../../components/RequestError'
import { LunarMap } from '../map'
import { LunarScene, GlobalMoonScene, useHeightmap } from '../scene'
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
import { HealthCard } from '../health/HealthCard'
import { useComparison } from '../comparison/useComparison'
import { buildComparisonRequest, newComparisonDraft } from './scenario'

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

export type ObservationWorkflow = 'now' | 'timeline' | 'comparison'

export function ObservationWorkspace({ workflow, onWorkflowChange, onOpenComparison, onCloseComparison }: { workflow: ObservationWorkflow; onWorkflowChange: (workflow: ObservationWorkflow) => void; onOpenComparison: () => void; onCloseComparison: () => void }) {
  const [draft, setDraft] = useState(initialScenario)
  const [comparisonScenarios, setComparisonScenarios] = useState(() => [newComparisonDraft(0), newComparisonDraft(1)])
  const comparisonValidationVersion = useRef(0)
  const comparisonCloseRef = useRef<HTMLButtonElement>(null)
  const [inspectedComparison, setInspectedComparison] = useState<{ label: string; model: string; dataset: string | null } | null>(null)
  const [category, setCategory] = useState<Site['category'] | ''>('')
  const [siteSearch, setSiteSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [catalog, setCatalog] = useState<SiteList | null>(null)
  const [catalogError, setCatalogError] = useState<ApiClientError | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [validation, setValidation] = useState<string | null>(null)
  const [coverage, setCoverage] = useState<TerrainCoverage | null>(null)
  const [coverageState, setCoverageState] = useState<'idle' | 'checking' | 'supported' | 'unsupported' | 'error'>('idle')
  const observation = useObservation()
  const timeline = useTimeline()
  const comparison = useComparison()
  const playback = useTimelinePlayback(timeline.result)
  const [layoutMode, setLayoutMode] = useState<'split' | 'enlarge-global' | 'enlarge-local'>('split')

  useEffect(() => {
    if (workflow !== 'comparison') return
    comparisonCloseRef.current?.focus()
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') onCloseComparison() }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [workflow, onCloseComparison])

  const coverageCoordinate = useMemo(() => draft.mode === 'catalog' && draft.site
    ? { latitude: draft.site.latitude, longitude: draft.site.longitude }
    : draft.mode === 'custom' && draft.latitude.trim() && draft.longitude.trim() &&
        Number.isFinite(Number(draft.latitude)) && Number.isFinite(Number(draft.longitude)) &&
        Number(draft.latitude) >= -90 && Number(draft.latitude) <= 90 && Number(draft.longitude) >= -180 && Number(draft.longitude) < 360
      ? { latitude: Number(draft.latitude), longitude: Number(draft.longitude) }
      : null, [draft.mode, draft.site, draft.latitude, draft.longitude])
  useEffect(() => {
    if (draft.horizonMode !== 'terrain' || !coverageCoordinate) {
      return
    }
    const controller = new AbortController()
    apiClient.getTerrainCoverage(coverageCoordinate.latitude, coverageCoordinate.longitude, { signal: controller.signal })
      .then((value) => { if (!controller.signal.aborted) { setCoverage(value); setCoverageState(value.available ? 'supported' : 'unsupported') } })
      .catch(() => { if (!controller.signal.aborted) { setCoverage(null); setCoverageState('error') } })
    return () => controller.abort()
  }, [draft.horizonMode, coverageCoordinate])

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
    comparisonValidationVersion.current += 1
    observation.reset()
    timeline.reset()
    setValidation(null)
    const next = { ...draft, ...patch }
    const validLocation = next.mode === 'catalog' ? next.site !== null :
      next.latitude.trim() !== '' && next.longitude.trim() !== '' &&
      Number.isFinite(Number(next.latitude)) && Number.isFinite(Number(next.longitude)) &&
      Number(next.latitude) >= -90 && Number(next.latitude) <= 90 && Number(next.longitude) >= -180 && Number(next.longitude) < 360
    const locationChanged = next.mode !== draft.mode || (next.mode === 'catalog'
      ? next.site?.id !== draft.site?.id
      : next.latitude !== draft.latitude || next.longitude !== draft.longitude)
    if (locationChanged || next.horizonMode !== draft.horizonMode) setCoverage(null)
    setCoverageState(next.horizonMode !== 'terrain' || !validLocation
      ? 'idle'
      : locationChanged || draft.horizonMode !== 'terrain'
        ? 'checking'
        : coverageState)
    setDraft(next)
  }

  function selectWorkflow(next: 'now' | 'timeline' | 'comparison') {
    comparisonValidationVersion.current += 1
    observation.reset()
    timeline.reset()
    setValidation(null)
    onWorkflowChange(next)
  }

  function submit(event: FormEvent) {
    event.preventDefault()
    if (workflow !== 'comparison' && draft.horizonMode === 'terrain' && coverageState !== 'supported') {
      setValidation(coverageState === 'checking' ? 'Terrain coverage is still being checked.' : coverageState === 'unsupported' ? 'Terrain is unavailable at this location. Choose geometric mode explicitly to continue.' : coverageState === 'error' ? 'Terrain coverage check failed. Retry the check before requesting terrain mode.' : 'Select a valid location to check terrain coverage.')
      return
    }
    try {
      setValidation(null)
      if (workflow === 'timeline')
        void timeline.submit(buildTimelineRequest(draft))
      else if (workflow === 'comparison') {
        const validationVersion = ++comparisonValidationVersion.current
        const request = buildComparisonRequest(comparisonScenarios, draft)
        void (async () => {
          if (request.horizon_mode === 'terrain') {
            const checks = await Promise.all(request.scenarios.map((scenario) => {
              const coordinates = comparisonScenarios.find((item) => item.label.trim() === scenario.label)
              const site = coordinates?.mode === 'catalog' ? coordinates.site : null
              const latitude = site?.latitude ?? ('latitude' in scenario.site ? scenario.site.latitude : NaN)
              const longitude = site?.longitude ?? ('longitude' in scenario.site ? scenario.site.longitude : NaN)
              return apiClient.getTerrainCoverage(latitude, longitude)
            }))
            const unavailable = checks.findIndex((check) => !check.available)
            if (validationVersion !== comparisonValidationVersion.current) return
            if (unavailable >= 0) throw new Error(`Terrain is unavailable for ${request.scenarios[unavailable].label}; choose geometric mode explicitly or remove that scenario.`)
            comparison.submit(request, Object.fromEntries(request.scenarios.map((scenario, index) => [scenario.label, checks[index]])))
            return
          }
          if (validationVersion !== comparisonValidationVersion.current) return
          comparison.submit(request)
        })().catch((error) => { if (validationVersion === comparisonValidationVersion.current) setValidation(error instanceof Error ? error.message : 'Unable to validate comparison terrain coverage.') })
      } else void observation.submit(buildRequest(draft), coverage)
    } catch (error) {
      observation.reset()
      timeline.reset()
      setValidation((error as Error).message)
    }
  }

  function inspectComparedScenario(label: string) {
    const frozen = comparison.resultRequest
    const entry = frozen?.scenarios.find((scenario) => scenario.label === label)
    const ranked = comparison.result?.ranked_scenarios.find((scenario) => scenario.label === label)
    if (!frozen || !entry || !ranked) return
    const site = entry.site
    const catalogSite = 'site_id' in site ? catalog?.items.find((item) => item.id === site.site_id) ?? null : null
    const nextDraft: ScenarioDraft = {
      mode: catalogSite ? 'catalog' : 'custom', site: catalogSite,
      name: 'name' in site ? site.name ?? ranked.site.name : ranked.site.name,
      latitude: String(ranked.site.latitude), longitude: String(ranked.site.longitude),
      utcTime: entry.start_time.slice(0, 19), durationDays: String(frozen.duration_days),
      stepMinutes: String(frozen.step_minutes), height: String(frozen.observer_height_m),
      margin: String(frozen.visibility_margin_deg), horizonMode: frozen.horizon_mode,
    }
    const request = {
      site, start_time: entry.start_time, duration_days: frozen.duration_days,
      step_minutes: frozen.step_minutes, horizon_mode: frozen.horizon_mode,
      observer_height_m: frozen.observer_height_m, visibility_margin_deg: frozen.visibility_margin_deg,
    }
    observation.reset()
    timeline.reset()
    setCoverage(null)
    setCoverageState(frozen.horizon_mode === 'terrain' ? 'checking' : 'idle')
    setDraft(nextDraft)
        onWorkflowChange('timeline')
    setInspectedComparison({
      label,
      model: ranked.provenance.model_version,
      dataset: ranked.provenance.terrain_dataset_id,
    })
    void timeline.submit(request)
  }

  const result = observation.result
  const timelineResult = timeline.result
  const comparisonResult = comparison.result
  const selectedPoint =
    workflow === 'timeline'
      ? timelineResult?.points[playback.activeIndex] ?? null
      : workflow === 'now' ? result?.point ?? null : null
  const activeJob = workflow === 'timeline' ? timeline : workflow === 'comparison' ? comparison : observation
  const busy = activeJob.busy
  const latitude = Number(draft.latitude)
  const longitude = Number(draft.longitude)
  // The map owns coordinate transformations; wait for server normalization outside its accepted longitude range.
  const displayedSite = workflow === 'timeline'
    ? timelineResult?.site
    : workflow === 'comparison'
      ? comparisonResult?.ranked_scenarios[0]?.site
      : result?.site
  const effectiveSite =
    displayedSite ?? (draft.mode === 'catalog' ? draft.site : null)
  const activeCatalogSite =
    displayedSite?.site_id
      ? catalog?.items.find((item) => item.id === displayedSite.site_id) ??
        (draft.site?.id === displayedSite.site_id ? draft.site : null)
      : draft.mode === 'catalog'
        ? draft.site
        : null
  const displayedCoverage = workflow === 'now' && result
    ? observation.resultCoverage
    : workflow === 'comparison' && comparisonResult
      ? comparison.resultCoverages[comparisonResult.ranked_scenarios[0].label] ?? null
      : coverage
  const terrainRegionId = activeCatalogSite?.terrain_region_id ?? displayedCoverage?.region_id ?? null
  const {
    heightmap,
    loading: isTerrainLoading,
    error: terrainError,
  } = useHeightmap(terrainRegionId)
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
          Choose a location and a UTC {workflow === 'timeline' ? 'period' : 'instant'} to inspect Sun and Earth visibility.
        </p>
      </div>
      <div className={`main-grid${workflow === 'comparison' ? ' comparison-active' : ''}`}>
        <nav className="activity-rail" aria-label="Workstation sections">
          <button type="button" aria-label="Landing sites" title="Landing sites" onClick={() => document.getElementById('landing-sites')?.scrollIntoView({ block: 'start' })}>⌖</button>
          <button type="button" aria-label="Timeline analysis" title="Timeline analysis" onClick={() => selectWorkflow('timeline')}>∿</button>
          <button type="button" aria-label="Global Moon layers" title="Global Moon layers" onClick={() => document.getElementById('map-heading')?.scrollIntoView({ block: 'center' })}>▱</button>
          <button type="button" aria-label="Comparison builder" title="Comparison builder" onClick={onOpenComparison}>⚖</button>
        </nav>
        <aside className="grid-sidebar">
          <section
            className="workspace-card"
            aria-labelledby="scenario-heading"
            role={workflow === 'comparison' ? 'dialog' : undefined}
            aria-modal={workflow === 'comparison' ? true : undefined}
          >
            <div className="card-heading"><h2 id="scenario-heading">{workflow === 'comparison' ? 'Compare sites' : 'Landing sites & analysis'}</h2>{workflow === 'comparison' && <button ref={comparisonCloseRef} type="button" className="secondary-button" onClick={onCloseComparison}>Close</button>}</div>
            <form onSubmit={submit} noValidate>
              <fieldset hidden={workflow === 'comparison'}>
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
              <fieldset hidden={workflow === 'comparison'}>
                <legend>Location</legend>
                <div className="segmented-control" role="group" aria-label="Location mode"><button type="button" aria-pressed={draft.mode === 'catalog'} onClick={() => change({ mode: 'catalog' })}>Catalog</button><button type="button" aria-pressed={draft.mode === 'custom'} onClick={() => change({ mode: 'custom' })}>Custom coords</button></div>
                {draft.mode === 'catalog' ? (
                  <>
                    <div className="category-filters" role="group" aria-label="Site category">{[['', 'All'], ['artemis', 'Artemis'], ['apollo', 'Apollo'], ['clps', 'CLPS'], ['international', 'International']].map(([value, label]) => <button key={value} type="button" aria-pressed={category === value} onClick={() => { reloadCatalog(value as typeof category, 0); change({ site: null }) }}>{label}</button>)}</div>
                    <label className="site-search"><span className="sr-only">Search landing sites</span><span aria-hidden="true">⌕</span><input type="search" placeholder="Search loaded sites…" value={siteSearch} onChange={(event) => setSiteSearch(event.target.value)} /></label>
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
                    <div className="site-card-list" role="listbox" aria-label="Landing sites" id="landing-sites">{(catalog?.items ?? []).filter((site) => `${site.name} ${site.description}`.toLowerCase().includes(siteSearch.trim().toLowerCase())).map((site) => <button type="button" role="option" aria-selected={draft.site?.id === site.id} className={`site-choice${draft.site?.id === site.id ? ' selected' : ''}`} key={site.id} onClick={() => change({ site })}><span className="site-dot" aria-hidden="true"/><span><strong>{site.name}</strong><small>{site.category.toUpperCase()} · {site.latitude.toFixed(2)}°, {site.longitude.toFixed(2)}°E</small></span><span aria-hidden="true">⋮</span></button>)}{catalog && !catalog.items.length && <p className="muted">No catalog sites are available.</p>}</div>
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
              {workflow === 'comparison' && <fieldset aria-label="Comparison scenarios">
                <legend>Scenarios ({comparisonScenarios.length}/6)</legend>
                {comparisonScenarios.map((scenario, index) => {
                  const update = (patch: Partial<typeof scenario>) => { comparisonValidationVersion.current += 1; setComparisonScenarios((items) => items.map((item, i) => i === index ? { ...item, ...patch } : item)) }
                  return <div className="comparison-scenario" key={index}>
                    <div className="card-heading"><strong>Scenario {index + 1}</strong><button type="button" className="secondary-button" disabled={comparisonScenarios.length <= 2} onClick={() => { comparisonValidationVersion.current += 1; setComparisonScenarios((items) => items.filter((_, i) => i !== index)) }}>Remove</button></div>
                    <label className="field">Unique label<input aria-label={`Scenario ${index + 1} label`} value={scenario.label} onChange={(event) => update({ label: event.target.value })} /></label>
                    <div className="mode-switch"><label><input type="radio" name={`scenario-site-${index}`} checked={scenario.mode === 'catalog'} onChange={() => update({ mode: 'catalog' })} /> Catalog</label><label><input type="radio" name={`scenario-site-${index}`} checked={scenario.mode === 'custom'} onChange={() => update({ mode: 'custom' })} /> Custom</label></div>
                    {scenario.mode === 'catalog' ? <label className="field">Site<select aria-label={`Scenario ${index + 1} site`} value={scenario.site?.id ?? ''} onChange={(event) => update({ site: catalog?.items.find((site) => site.id === event.target.value) ?? null })}><option value="">Choose a site</option>{catalog?.items.map((site) => <option key={site.id} value={site.id}>{site.name}</option>)}</select></label> : <>
                      <label className="field">Custom site name<input value={scenario.name} onChange={(event) => update({ name: event.target.value })} /></label>
                      <div className="field-pair"><label className="field">Latitude<input aria-label={`Scenario ${index + 1} latitude`} type="number" value={scenario.latitude} onChange={(event) => update({ latitude: event.target.value })} /></label><label className="field">Longitude east<input aria-label={`Scenario ${index + 1} longitude`} type="number" value={scenario.longitude} onChange={(event) => update({ longitude: event.target.value })} /></label></div>
                    </>}
                    <label className="field">Start date and time (UTC)<input aria-label={`Scenario ${index + 1} start time`} type="datetime-local" step="1" min="2000-01-01T00:00:00" max="2049-12-31T23:59:59" value={scenario.utcTime} onChange={(event) => update({ utcTime: event.target.value })} /></label>
                  </div>
                })}
                <button type="button" className="secondary-button" disabled={comparisonScenarios.length >= 6} onClick={() => { comparisonValidationVersion.current += 1; setComparisonScenarios((items) => [...items, newComparisonDraft(items.length, draft.utcTime)]) }}>Add scenario</button>
              </fieldset>}
              <fieldset>
                <legend>Time & model</legend>
                {workflow !== 'comparison' && <label className="field">
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
                </label>}
                <p className="field-help">
                  Enter UTC explicitly, regardless of your device time zone. Supported years: 2000–2049; whole seconds.
                </p>
                {workflow !== 'now' && (
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
                <details className="advanced-settings">
                  <summary>Observer & visibility settings</summary>
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
                </details>
                <p className="field-help">
                  Geometric mode uses the local reference horizon. Terrain mode uses prepared elevation data; the scene mesh is for display.
                </p>
                <div className="horizon-control" role="group" aria-label="Horizon mode"><span>Horizon mode</span><div className="segmented-control"><button type="button" aria-pressed={draft.horizonMode === 'geometric'} onClick={() => change({ horizonMode: 'geometric' })}>Geometric</button><button type="button" aria-pressed={draft.horizonMode === 'terrain'} onClick={() => change({ horizonMode: 'terrain' })}>Terrain</button></div></div>
                {draft.horizonMode === 'terrain' && <p role={coverageState === 'error' || coverageState === 'unsupported' ? 'alert' : 'status'} className="field-help">
                  {coverageState === 'checking' && 'Checking terrain coverage…'}
                  {coverageState === 'supported' && `Terrain supported${coverage?.dataset_id ? ` · ${coverage.dataset_id}` : ''}${coverage?.resolution_m != null ? ` · ${coverage.resolution_m} m` : ''}`}
                  {coverageState === 'unsupported' && `Terrain unavailable${coverage?.reason ? `: ${coverage.reason}` : ''}. Choose geometric mode explicitly to continue.`}
                  {coverageState === 'error' && 'Terrain coverage check failed. Retry by changing the location or mode.'}
                  {coverageState === 'idle' && 'Select a valid location to check terrain coverage.'}
                </p>}
              </fieldset>
              {validation && (
                <p role="alert" className="request-error">
                  {validation}
                </p>
              )}
              <button className="primary-button" type="submit">
                {busy
                  ? workflow === 'timeline' ? 'Replace with new timeline' : 'Replace with new observation'
                  : workflow === 'timeline' ? 'Request timeline' : workflow === 'comparison' ? 'Compare scenarios' : 'Request observation'}
              </button>
            </form>
            <div className="job-progress" role="status" aria-live="polite">
              <span
                className={
                  busy ? 'progress-dot active' : 'progress-dot'
                }
              />
              {workflow === 'comparison'
                ? { idle: 'No comparison requested', submitting: 'Submitting comparison…', queued: 'Queued — waiting for the worker', running: 'Ranking scenarios…', 'loading-result': 'Loading comparison result…', succeeded: 'Comparison ready', failed: 'Comparison failed', error: 'Comparison request could not be completed' }[comparison.phase]
                : workflow === 'timeline'
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
          <div className="visual-grid" data-layout-mode={layoutMode}>
            <section
              className={`workspace-card visual-card ${layoutMode === 'enlarge-global' ? 'visual-card-enlarged' : ''}`}
              aria-labelledby="map-heading"
              style={layoutMode === 'enlarge-global' ? { gridColumn: '1 / -1' } : undefined}
            >
              <div className="card-heading" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h2 id="map-heading">Global Moon view</h2>
                <button
                  type="button"
                  className="secondary-button"
                  style={{ padding: '2px 8px', fontSize: '0.72rem' }}
                  onClick={() => setLayoutMode(layoutMode === 'enlarge-global' ? 'split' : 'enlarge-global')}
                  title="Toggle enlarged view for Global Moon"
                  data-testid="toggle-enlarge-global"
                >
                  {layoutMode === 'enlarge-global' ? 'Restore Split' : 'Enlarge Globe'}
                </button>
              </div>
              <p className="muted">
                Complete spherical Moon in MCMF coordinates with active Earth communication link · drag to orbit, scroll to zoom.
              </p>

              {/* 3D Global Moon Viewport (Dominant Stage 5 view) */}
              <div
                className="map-viewport"
                data-testid="global-moon-viewport"
                style={{
                  height: layoutMode === 'enlarge-global' ? '520px' : '360px',
                  marginBottom: '10px',
                }}
              >
                <GlobalMoonScene
                  catalogSites={catalog?.items}
                  selectedSite={effectiveSite}
                  selectedCoordinate={coordinate || null}
                  observationPoint={selectedPoint}
                  isLoading={busy}
                  dataStatus={(workflow === 'timeline' ? timelineResult?.meta.data_status : result?.meta.data_status) ?? null}
                  onSelectCoordinate={(val) =>
                    change({
                      mode: 'custom',
                      latitude: String(val.latitude),
                      longitude: String(val.longitude),
                    })
                  }
                  onSelectSite={(site) => {
                    change({
                      mode: 'catalog',
                      site,
                      latitude: String(site.latitude),
                      longitude: String(site.longitude),
                    })
                  }}
                />
              </div>

              {/* Registered 2D Layer Map with Layer Switching */}
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
                <details className="layer-map-drawer" style={{ marginTop: '8px' }}>
                  <summary style={{ cursor: 'pointer', fontSize: '0.75rem', color: '#a0a5b5', padding: '4px 0' }}>
                    2D Projections & Map Layers (LROC / Moon Trek)
                  </summary>
                  <div style={{ marginTop: '6px' }}>
                    <LunarMap
                      layers={mapLayers.items}
                      quickmapUrl={activeCatalogSite?.quickmap_url ?? null}
                      selectedCoordinate={coordinate || null}
                      selectedSiteId={displayedSite?.site_id ?? (draft.mode === 'catalog' ? draft.site?.id : null)}
                      onSelectCoordinate={(value) =>
                        change({
                          mode: 'custom',
                          latitude: String(value.latitude),
                          longitude: String(value.longitude),
                        })
                      }
                    />
                  </div>
                </details>
              )}
              <p className="field-help">
                Spherical MCMF frame with authoritative Earth/Sun vectors and communication line. Registered Moon Trek / LROC imagery below.
              </p>
            </section>
            <section
              className={`workspace-card visual-card ${layoutMode === 'enlarge-local' ? 'visual-card-enlarged' : ''}`}
              aria-labelledby="scene-heading"
              style={layoutMode === 'enlarge-local' ? { gridColumn: '1 / -1' } : undefined}
            >
              <div className="card-heading" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h2 id="scene-heading">Local terrain inspector</h2>
                <button
                  type="button"
                  className="secondary-button"
                  style={{ padding: '2px 8px', fontSize: '0.72rem' }}
                  onClick={() => setLayoutMode(layoutMode === 'enlarge-local' ? 'split' : 'enlarge-local')}
                  title="Enlarge local terrain inspector"
                  data-testid="toggle-enlarge-local"
                >
                  {layoutMode === 'enlarge-local' ? 'Restore Split' : 'Enlarge Scene'}
                </button>
              </div>

              {/* Site Inspector Summary Panel matching Image 2 */}

              <p className="muted">
                Schematic local ENU scene · directions from the observation API.
              </p>
              <div
                className="scene-viewport"
                style={{
                  height: layoutMode === 'enlarge-local' ? '560px' : undefined,
                }}
              >
                <LunarScene
                  observationPoint={selectedPoint}
                  site={effectiveSite}
                  dataStatus={(workflow === 'timeline' ? timelineResult?.meta.data_status : result?.meta.data_status) ?? null}
                  sunDirectionEnu={selectedPoint?.sun.direction_enu ?? null}
                  earthDirectionEnu={selectedPoint?.earth.direction_enu ?? null}
                  observerHeightM={workflow === 'comparison' ? comparison.resultRequest?.observer_height_m : workflow === 'timeline' ? timelineResult?.site.observer_height_m : result?.site.observer_height_m ?? Number(draft.height)}
                  horizonMode={(workflow === 'comparison' ? comparisonResult?.meta.horizon_mode : workflow === 'timeline' ? timelineResult?.meta.horizon_mode : result?.meta.horizon_mode) ?? draft.horizonMode}
                  terrainDatasetId={(workflow === 'comparison' ? comparisonResult?.ranked_scenarios[0]?.provenance.terrain_dataset_id : workflow === 'timeline' ? timelineResult?.meta.terrain_dataset_id : result?.meta.terrain_dataset_id) ?? null}
                  visibilityMarginDeg={workflow === 'comparison' ? comparison.resultRequest?.visibility_margin_deg : workflow === 'now' && result ? observation.resultRequest?.visibility_margin_deg : Number(draft.margin)}
                  isLoading={busy}
                  heightmap={heightmap}
                  isTerrainLoading={isTerrainLoading}
                  terrainError={terrainError}
                />
              </div>
              <p className="field-help">
                Marker distances are for display; terrain mesh shows local numerical geometry when available.
              </p>
            </section>
          </div>
          <section className="workspace-card observation-inspector" aria-label="Site inspector">
            <div className="card-heading"><h2>Site inspector</h2></div>
            <div className="site-inspector-grid" data-testid="site-inspector-panel">
              <span className="site-inspector-label">Site</span>
              <span className="site-inspector-value">{effectiveSite?.name ?? (coordinate ? `${coordinate.latitude.toFixed(2)}°, ${coordinate.longitude.toFixed(2)}°` : 'No site selected')}</span>
              <span className="site-inspector-label">Sun elevation</span>
              <span className="site-inspector-value">{selectedPoint ? `${selectedPoint.sun.elevation_deg.toFixed(1)}°` : '—'}</span>
              <span className="site-inspector-label">Earth visibility</span>
              <span className="site-inspector-value">{selectedPoint ? (selectedPoint.earth.visible ? 'Visible' : 'Not visible') : '—'}</span>
              <span className="site-inspector-label">Horizon mode</span>
              <span className="site-inspector-value">{((workflow === 'comparison' ? comparisonResult?.meta.horizon_mode : workflow === 'timeline' ? timelineResult?.meta.horizon_mode : result?.meta.horizon_mode) ?? draft.horizonMode) === 'terrain' ? 'Terrain' : 'Geometric'}</span>
              <span className="site-inspector-label">Data status</span>
              <span className="site-inspector-value">{(workflow === 'timeline' ? timelineResult?.meta.data_status : workflow === 'comparison' ? comparisonResult?.meta.data_status : result?.meta.data_status) ?? '—'}</span>
            </div>
            {workflow === 'now'
              ? <ObservationResult result={result} request={observation.resultRequest} coverage={observation.resultCoverage} />
              : workflow === 'timeline'
                ? <><div className="card-heading"><h2>Site inspector</h2>{timelineResult && <span className={`data-badge ${timelineResult.meta.data_status}`}>{timelineResult.meta.data_status}</span>}</div>{timelineResult && selectedPoint ? <><strong>{timelineResult.site.name}</strong><p className="muted">{selectedPoint.timestamp} UTC · {timelineResult.meta.horizon_mode} horizon</p><div className="inspector-values"><span>Sun elevation <b>{selectedPoint.sun.elevation_deg}°</b></span><span>Sun horizon <b>{selectedPoint.sun.horizon_elevation_deg}°</b></span><span>Sun visible <b>{selectedPoint.sun.visible ? 'Yes' : 'No'}</b></span><span>Earth elevation <b>{selectedPoint.earth.elevation_deg}°</b></span><span>Earth horizon <b>{selectedPoint.earth.horizon_elevation_deg}°</b></span><span>Earth visible <b>{selectedPoint.earth.visible ? 'Yes' : 'No'}</b></span></div></> : <p className="muted">Site and returned sample values appear here after timeline analysis.</p>}</>
                : <><div className="card-heading"><h2>Comparison inspector</h2></div>{comparisonResult ? <p>{comparisonResult.recommended_label} · {comparisonResult.recommendation_reason}</p> : <p className="muted">Comparison results appear below after the job completes.</p>}</>}
          </section>
          <div className="workstation-bottom">
          {workflow === 'timeline' ? (
            timelineResult ? (
              <>
                {inspectedComparison && <p className="field-help">Detailed timeline for {inspectedComparison.label}: model {timelineResult.meta.model_version}, terrain dataset {timelineResult.meta.terrain_dataset_id ?? 'none'}. Comparison used model {inspectedComparison.model}, terrain dataset {inspectedComparison.dataset ?? 'none'}{timelineResult.meta.model_version !== inspectedComparison.model || timelineResult.meta.terrain_dataset_id !== inspectedComparison.dataset ? ' — versions differ; this detail result is not an exact model/dataset match.' : ' — model and dataset match the comparison metadata.'}</p>}
                <TimelineAnalytics result={timelineResult} playback={playback} />
              </>
            ) : (
              <section className="workspace-card" aria-label="Timeline result">
                <h2>Timeline analysis</h2>
                <p className="muted">Submit a period to load returned samples, intervals, and summary metrics.</p>
              </section>
            )
          ) : (
            <>
              {result && observation.resultRequest && <p className="muted">Displayed result uses {observation.resultRequest.horizon_mode} mode and its submitted scenario settings{observation.busy ? '; a new calculation is running' : ''}. Form edits do not change this result.</p>}
              <section className="workspace-card analytics-empty" aria-label="Timeline and analytics">
                <div className="card-heading"><h2>{workflow === 'comparison' ? 'Comparison analytics' : 'Timeline & analytics'}</h2></div>
                <p className="muted">{workflow === 'comparison' ? 'A completed backend comparison and its returned metrics will appear here.' : 'No timeline requested. Returned samples, elevation plots, intervals, and metrics will appear here after analysis.'}</p>
                {workflow === 'now' && <button type="button" className="secondary-button" onClick={() => selectWorkflow('timeline')}>Set up a timeline</button>}
              </section>
            </>
          )}
          {comparisonResult && <section className="workspace-card comparison-results" aria-label="Comparison results">
            <div className="card-heading"><h2>Scenario ranking</h2><span className={`data-badge ${comparisonResult.meta.data_status}`}>{comparisonResult.meta.data_status}</span></div>
            {(comparison.busy || comparison.phase === 'error' || comparison.phase === 'failed') && <p className="muted">Showing the last completed comparison while the newer request is {comparison.busy ? 'running' : 'unavailable'}.</p>}
            <p><strong>Recommendation:</strong> {comparisonResult.recommended_label}. {comparisonResult.recommendation_reason}</p>
            <p className="field-help">v1 product score = 40% sunlight + 30% Earth visibility + 30% golden-window time. It is not an official NASA safety certification. Equal displayed scores may retain different backend ranks because ranking uses unrounded values and tie-breaks.</p>
            <div className="table-scroll"><table className="observation-table"><caption>Backend rank and returned metrics, in backend order</caption><thead><tr><th>Rank</th><th>Scenario / site</th><th>Start (UTC)</th><th>Sunlit</th><th>Earth visible</th><th>Golden</th><th>Longest golden</th><th>Score</th><th>Detail</th></tr></thead><tbody>{comparisonResult.ranked_scenarios.map((item) => <tr key={item.rank}><td>{item.rank}</td><th scope="row">{item.label}<br /><span className="muted">{item.site.name}</span></th><td>{item.start_time}</td><td>{item.summary.sunlit_pct}%</td><td>{item.summary.earth_visible_pct}%</td><td>{item.summary.golden_pct}%</td><td>{item.summary.longest_golden_window_hours} h</td><td>{item.score.toFixed(1)}</td><td><button type="button" className="secondary-button" onClick={() => inspectComparedScenario(item.label)}>Open timeline</button></td></tr>)}</tbody></table></div>
            <details><summary>Comparison provenance</summary><p>Ranking model {comparisonResult.meta.model_version} · {comparisonResult.meta.horizon_mode} · {comparisonResult.meta.time_resolution_minutes} minute samples · shared terrain dataset {comparisonResult.meta.terrain_dataset_id ?? 'multiple or none'}</p><h3>Scenario data provenance</h3><ul className="source-list">{comparisonResult.ranked_scenarios.map((scenario) => <li key={scenario.label}><strong>{scenario.label}</strong><p className="muted">Model {scenario.provenance.model_version} · terrain dataset {scenario.provenance.terrain_dataset_id ?? 'none'}</p><ul>{scenario.provenance.sources.map((source, index) => <li key={`${source.name}-${index}`}><SourceLink url={source.url}>{source.name}</SourceLink><p className="muted">Version {source.version ?? 'not reported'} · Retrieved {source.fetched_at}</p></li>)}</ul></li>)}</ul></details>
          </section>}
          </div>
        </div>
      </div>
    </main>
  )
}
