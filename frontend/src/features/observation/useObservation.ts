import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient } from '../../api/client'
import { ApiClientError } from '../../api/errors'
import type { NowRequest, NowResult, TerrainCoverage } from '../../api/types'

type Phase =
  | 'idle'
  | 'submitting'
  | 'queued'
  | 'running'
  | 'loading-result'
  | 'succeeded'
  | 'failed'
  | 'error'
interface ObservationState {
  phase: Phase
  result: NowResult | null
  error: ApiClientError | null
  jobId?: string
  request?: NowRequest
  resultRequest?: NowRequest
  resultCoverage?: TerrainCoverage | null
}
const idle: ObservationState = { phase: 'idle', result: null, error: null }

export function useObservation() {
  const [state, setState] = useState<ObservationState>(idle)
  const sequence = useRef(0)
  const controller = useRef<AbortController | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const stop = useCallback(() => {
    sequence.current += 1
    controller.current?.abort()
    if (timer.current !== null) clearTimeout(timer.current)
    timer.current = null
  }, [])
  const reset = useCallback(() => {
    stop()
    setState((previous) => ({ ...idle, result: previous.result, resultRequest: previous.resultRequest, resultCoverage: previous.resultCoverage }))
  }, [stop])
  useEffect(() => stop, [stop])

  const submit = useCallback(
    async (request: NowRequest, coverage?: TerrainCoverage | null) => {
      stop()
      const current = sequence.current
      const abort = new AbortController()
      controller.current = abort
      const active = () => current === sequence.current && !abort.signal.aborted
      setState((previous) => ({ phase: 'submitting', result: previous.result, error: null, request }))
      const fail = (error: unknown) => {
        if (active())
          setState((previous) => ({
            ...previous,
            phase: 'error',
            error:
              error instanceof ApiClientError
                ? error
                : new ApiClientError({
                    message: 'Unable to complete the observation request.',
                    cause: error,
                  }),
          }))
      }
      try {
        const accepted = await apiClient.submitNow(request, {
          signal: abort.signal,
        })
        if (!active()) return
        setState((previous) => ({
          phase: 'queued',
          result: previous.result,
          error: null,
          jobId: accepted.job_id,
          request,
          resultRequest: previous.resultRequest,
          resultCoverage: previous.resultCoverage,
        }))
        const poll = async () => {
          try {
            const job = await apiClient.getJob(accepted.status_url, {
              signal: abort.signal,
            })
            if (!active()) return
            if (job.status === 'failed') {
              setState({
                phase: 'failed',
                result: state.result,
                jobId: accepted.job_id,
                request,
                resultRequest: state.resultRequest,
                resultCoverage: state.resultCoverage,
                error: new ApiClientError({
                  ...job.error!,
                  requestId: job.error!.request_id,
                }),
              })
            } else if (job.status === 'succeeded') {
              setState((previous) => ({ ...previous, phase: 'loading-result' }))
              const result = await apiClient.getResult(accepted.result_url, {
                signal: abort.signal,
              })
              if (active())
                setState({
                  phase: 'succeeded',
                  result,
                  error: null,
                  jobId: accepted.job_id,
                  request,
                  resultRequest: request,
                  resultCoverage: coverage ?? null,
                })
            } else {
              setState((previous) => ({
                ...previous,
                phase: job.status as 'queued' | 'running',
              }))
              timer.current = setTimeout(() => {
                void poll()
              }, 2000)
            }
          } catch (error) {
            fail(error)
          }
        }
        timer.current = setTimeout(() => {
          void poll()
        }, 2000)
      } catch (error) {
        fail(error)
      }
    },
    [stop, state.result, state.resultRequest, state.resultCoverage],
  )

  return {
    ...state,
    submit,
    reset,
    busy: ['submitting', 'queued', 'running', 'loading-result'].includes(
      state.phase,
    ),
  }
}
