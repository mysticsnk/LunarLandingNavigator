/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type {
  CSAResources,
  ComparisonRequest,
  ComparisonResult,
  Job,
  JobAccepted,
  NowRequest,
  NowResult,
  SiteList,
  TimelineResult,
  Heightmap,
} from '../api/types'

// Test-only synthetic examples; these are not measured scientific results.
function example<T>(name: string): T {
  return JSON.parse(
    readFileSync(
      resolve(
        dirname(fileURLToPath(import.meta.url)),
        '../../../contracts/examples',
        `${name}.json`,
      ),
      'utf8',
    ),
  ) as T
}
export const accepted = example<JobAccepted>('job-accepted-now')
export const observationResult = example<NowResult>('observation-result')
export const timelineAccepted = example<JobAccepted>('job-accepted')
export const timelineResult = example<TimelineResult>('timeline-two-golden-windows')
export const comparisonAccepted = example<JobAccepted>('job-accepted-comparison')
export const comparisonResult = example<ComparisonResult>('comparison-result')
export const comparisonRequest = example<ComparisonRequest>('comparison-request')
export const queued: Job = { ...example<Job>('job-queued'), kind: 'now' }
export const running: Job = { ...example<Job>('job-running'), kind: 'now' }
export const failed: Job = { ...example<Job>('job-failed'), kind: 'now' }
export const succeeded: Job = {
  ...running,
  status: 'succeeded',
  finished_at: '2027-07-15T00:00:02Z',
}
export const comparisonSucceeded: Job = { ...succeeded, kind: 'comparison' }
export const request: NowRequest = {
  site: { latitude: -89.44, longitude: 222.1 },
  target_time: '2027-07-15T00:00:00Z',
  horizon_mode: 'geometric',
  observer_height_m: 2,
  visibility_margin_deg: 0,
}
export const catalog: SiteList = {
  items: [
    {
      id: 'development-site',
      name: 'Synthetic catalog site',
      category: 'artemis',
      latitude: -89.44,
      longitude: -137.9,
      description: 'Development catalog fixture.',
      source_url: 'https://example.org/site-fixture',
      quickmap_url: 'https://example.org/quickmap-fixture',
      terrain_region_id: null,
    },
  ],
  total: 1,
  limit: 50,
  offset: 0,
}
export const resources: CSAResources = {
  items: [],
  fetched_at: '2027-07-15T00:00:00Z',
  data_status: 'fresh',
}
export const resourceItem = {
  id: 'synthetic-news',
  title: 'Synthetic Moon news',
  summary: 'Test-only summary.',
  url: 'https://example.org/news-fixture',
  published_at: '2027-07-14T12:00:00Z',
  topics: ['Moon'],
}

export const heightmapFixture: Heightmap = {
  region_id: 'shackleton_connecting_ridge',
  dataset_id: 'LDEM_80S_20MPP_ADJ',
  model_version: 'stage4-dem-v1',
  frame: 'local_enu',
  origin: {
    latitude: -89.44,
    longitude: -137.9,
    elevation_m: 1250.0,
  },
  east_min_m: -100,
  north_min_m: -100,
  spacing_m: 50,
  width: 5,
  height: 5,
  elevation_m: [
    0, 2, 5, 2, 0,
    1, 4, 8, 4, 1,
    3, 6, 12, 6, 3,
    1, 4, 8, 4, 1,
    0, 2, 5, 2, 0,
  ],
  source_url: 'https://pgda.gsfc.nasa.gov/products/90',
  attribution: 'NASA/GSFC/LOLA Team; LDEM 80S 20m/px.',
}

export function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}
