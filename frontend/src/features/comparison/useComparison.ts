import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient } from '../../api/client'
import { ApiClientError } from '../../api/errors'
import type { ComparisonRequest, ComparisonResult, TerrainCoverage } from '../../api/types'

type Phase = 'idle' | 'submitting' | 'queued' | 'running' | 'loading-result' | 'succeeded' | 'failed' | 'error'
interface State {
  phase: Phase
  result: ComparisonResult | null
  request: ComparisonRequest | null
  resultRequest: ComparisonRequest | null
  resultCoverages: Record<string, TerrainCoverage>
  error: ApiClientError | null
  jobId?: string
}
const idle: State = { phase: 'idle', result: null, request: null, resultRequest: null, resultCoverages: {}, error: null }

export function useComparison() {
  const [state, setState] = useState(idle)
  const sequence = useRef(0)
  const controller = useRef<AbortController | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const stop = useCallback(() => {
    sequence.current += 1
    controller.current?.abort()
    if (timer.current !== null) clearTimeout(timer.current)
    timer.current = null
  }, [])
  const reset = useCallback(() => { stop(); setState(idle) }, [stop])
  useEffect(() => stop, [stop])

  const submit = useCallback(async (request: ComparisonRequest, coverages: Record<string, TerrainCoverage> = {}) => {
    stop()
    const current = sequence.current
    const abort = new AbortController()
    controller.current = abort
    const active = () => current === sequence.current && !abort.signal.aborted
    setState((previous) => ({ ...previous, phase: 'submitting', request, error: null }))
    const fail = (error: unknown) => {
      if (active()) setState((previous) => ({ ...previous, phase: 'error', error: error instanceof ApiClientError ? error : new ApiClientError({ message: 'Unable to complete the comparison request.', cause: error }) }))
    }
    try {
      const accepted = await apiClient.submitComparison(request, { signal: abort.signal })
      if (!active()) return
      setState((previous) => ({ ...previous, phase: 'queued', request, error: null, jobId: accepted.job_id }))
      const poll = async () => {
        try {
          const job = await apiClient.getJob(accepted.status_url, { signal: abort.signal })
          if (!active()) return
          if (job.kind !== 'comparison') throw new ApiClientError({ code: 'INVALID_RESPONSE_FORMAT', message: 'The API returned a non-comparison job.' })
          if (job.status === 'failed') {
            setState((previous) => ({ ...previous, phase: 'failed', error: new ApiClientError({ ...job.error!, requestId: job.error!.request_id }) }))
          } else if (job.status === 'succeeded') {
            setState((previous) => ({ ...previous, phase: 'loading-result' }))
            const result = await apiClient.getComparisonResult(accepted.result_url, { signal: abort.signal })
            if (result.meta.horizon_mode !== request.horizon_mode || result.meta.time_resolution_minutes !== request.step_minutes)
              throw new ApiClientError({ code: 'INVALID_RESPONSE_FORMAT', message: 'The comparison result does not match the submitted shared settings.' })
            if (active()) setState((previous) => ({ ...previous, phase: 'succeeded', result, request, resultRequest: request, resultCoverages: coverages, error: null, jobId: accepted.job_id }))
          } else {
            setState((previous) => ({ ...previous, phase: job.status as 'queued' | 'running' }))
            timer.current = setTimeout(() => void poll(), 2000)
          }
        } catch (error) { fail(error) }
      }
      timer.current = setTimeout(() => void poll(), 2000)
    } catch (error) { fail(error) }
  }, [stop])

  return { ...state, submit, reset, busy: ['submitting', 'queued', 'running', 'loading-result'].includes(state.phase) }
}
