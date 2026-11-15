import type { ComparisonRequest, NowRequest, Site, TimelineRequest } from '../../api/types'

export interface ScenarioDraft {
  mode: 'catalog' | 'custom'
  site: Site | null
  name: string
  latitude: string
  longitude: string
  utcTime: string
  durationDays: string
  stepMinutes: string
  height: string
  margin: string
  horizonMode: 'geometric' | 'terrain'
}

export interface ComparisonDraft {
  label: string
  mode: 'catalog' | 'custom'
  site: Site | null
  name: string
  latitude: string
  longitude: string
  utcTime: string
}

export function newComparisonDraft(index: number, utcTime = new Date().toISOString().slice(0, 19)): ComparisonDraft {
  return { label: `Scenario ${index + 1}`, mode: 'catalog', site: null, name: '', latitude: '', longitude: '', utcTime }
}

export function initialScenario(): ScenarioDraft {
  return {
    mode: 'catalog',
    site: null,
    name: '',
    latitude: '',
    longitude: '',
    utcTime: new Date().toISOString().slice(0, 19),
    durationDays: '14',
    stepMinutes: '120',
    height: '2',
    margin: '0',
    horizonMode: 'geometric',
  }
}

export function serializeUtc(value: string): string {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(value))
    throw new Error('Choose a UTC date and time, with whole seconds.')
  const seconds = value.length === 16 ? value + ':00' : value
  const time = new Date(seconds + 'Z')
  if (
    !Number.isFinite(time.getTime()) ||
    time.toISOString().slice(0, 19) !== seconds
  )
    throw new Error('Choose a valid UTC date and time.')
  if (seconds < '2000-01-01T00:00:00' || seconds >= '2050-01-01T00:00:00')
    throw new Error(
      'Observation time must be from 2000-01-01 up to, but excluding, 2050-01-01 UTC.',
    )
  return seconds + 'Z'
}

function bounded(
  value: string,
  name: string,
  minimum: number,
  maximum: number,
  exclusive = false,
): number {
  const number = Number(value)
  if (
    !value.trim() ||
    !Number.isFinite(number) ||
    number < minimum ||
    (exclusive ? number >= maximum : number > maximum)
  ) {
    throw new Error(
      `${name} must be ${minimum} to ${maximum}${exclusive ? ' (upper bound excluded)' : ''}.`,
    )
  }
  return number
}

export function buildRequest(draft: ScenarioDraft): NowRequest {
  const target_time = serializeUtc(draft.utcTime)
  const observer_height_m = bounded(
    draft.height,
    'Observer height in metres',
    0,
    20,
  )
  const visibility_margin_deg = bounded(
    draft.margin,
    'Visibility margin in degrees',
    0,
    5,
  )
  if (draft.mode === 'catalog' && !draft.site)
    throw new Error('Select a catalog site or enter custom coordinates.')
  const site =
    draft.mode === 'catalog'
      ? { site_id: draft.site!.id }
      : {
          ...(draft.name.trim() ? { name: draft.name.trim() } : {}),
          latitude: bounded(draft.latitude, 'Latitude', -90, 90),
          longitude: bounded(draft.longitude, 'Longitude', -180, 360, true),
        }
  return {
    site,
    target_time,
    horizon_mode: draft.horizonMode,
    observer_height_m,
    visibility_margin_deg,
  }
}

export function buildTimelineRequest(draft: ScenarioDraft): TimelineRequest {
  const { target_time, ...shared } = buildRequest(draft)
  const duration_days = Number(draft.durationDays)
  if (!Number.isInteger(duration_days) || duration_days < 1 || duration_days > 30)
    throw new Error('Duration must be a whole number from 1 to 30 days.')
  const step_minutes = Number(draft.stepMinutes)
  if (![15, 30, 60, 120, 180, 360].includes(step_minutes))
    throw new Error('Choose a supported sampling step.')
  const endTime = Date.parse(target_time) + duration_days * 86_400_000
  if (endTime > Date.parse('2050-01-01T00:00:00Z'))
    throw new Error('The requested period must end by 2050-01-01T00:00:00Z.')
  return {
    ...shared,
    start_time: target_time,
    duration_days,
    step_minutes: step_minutes as TimelineRequest['step_minutes'],
  }
}

export function buildComparisonRequest(scenarios: ComparisonDraft[], common: ScenarioDraft): ComparisonRequest {
  if (scenarios.length < 2 || scenarios.length > 6) throw new Error('Compare between 2 and 6 scenarios.')
  const labels = scenarios.map((scenario) => scenario.label.trim())
  if (labels.some((label) => !label)) throw new Error('Every scenario needs a label.')
  if (new Set(labels.map((label) => label.toLocaleLowerCase())).size !== labels.length) throw new Error('Scenario labels must be unique.')
  const observer_height_m = bounded(common.height, 'Observer height in metres', 0, 20)
  const visibility_margin_deg = bounded(common.margin, 'Visibility margin in degrees', 0, 5)
  const duration_days = bounded(common.durationDays, 'Duration in days', 1, 30)
  if (!Number.isInteger(duration_days)) throw new Error('Duration must be a whole number from 1 to 30 days.')
  const step_minutes = Number(common.stepMinutes)
  if (![15, 30, 60, 120, 180, 360].includes(step_minutes)) throw new Error('Choose a supported sampling step.')
  const scenariosRequest = scenarios.map((scenario, index) => {
    const start_time = serializeUtc(scenario.utcTime)
    if (Date.parse(start_time) + duration_days * 86_400_000 > Date.parse('2050-01-01T00:00:00Z'))
      throw new Error(`${labels[index]} ends after the supported UTC range.`)
    const site = scenario.mode === 'catalog'
      ? scenario.site ? { site_id: scenario.site.id } : null
      : {
          ...(scenario.name.trim() ? { name: scenario.name.trim() } : {}),
          latitude: bounded(scenario.latitude, 'Latitude', -90, 90),
          longitude: bounded(scenario.longitude, 'Longitude', -180, 360, true),
        }
    if (!site) throw new Error(`Choose a site for ${labels[index]}.`)
    return { label: labels[index], site, start_time }
  })
  return {
    scenarios: scenariosRequest,
    duration_days,
    step_minutes: step_minutes as ComparisonRequest['step_minutes'],
    horizon_mode: common.horizonMode,
    observer_height_m,
    visibility_margin_deg,
  }
}
