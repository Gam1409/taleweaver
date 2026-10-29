import { apiFetch } from '@/services/http'
import { updateVisualProgress, clearVisualProgress, visualStageLabel } from './visualJobProgress'

interface JobStatus {
  id: string
  state: 'queued' | 'running' | 'succeeded' | 'failed' | 'abandoned'
  stage?: string | null
  message: string
  result: Record<string, unknown> | null
}

async function readResponse(response: Response): Promise<JobStatus> {
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Invalid image job request.')
  return data as JobStatus
}

export async function runVisualJob(
  operation: 'test' | 'asset' | 'catalog' | 'avatar' | 'session_npc' | 'session_illustration',
  payload: unknown,
  templateId?: string,
  signal?: AbortSignal,
  sessionId?: string,
): Promise<Record<string, unknown>> {
  const id = crypto.randomUUID()
  const path = `/settings/visual-jobs/${id}`
  const cancel = (): void => {
    void apiFetch(path, { method: 'DELETE' }).catch(() => undefined)
  }
  if (signal?.aborted) throw new DOMException('Generation abandoned', 'AbortError')
  signal?.addEventListener('abort', cancel, { once: true })
  try {
    let job = await readResponse(await apiFetch('/settings/visual-jobs', {
      method: 'POST', includeJson: true, signal,
      body: JSON.stringify({ id, operation, template_id: templateId, session_id: sessionId, payload }),
    }))
    updateVisualProgress(id, job.stage)
    while (job.state === 'queued' || job.state === 'running') {
      await new Promise(resolve => window.setTimeout(resolve, 1000))
      if (signal?.aborted) throw new DOMException('Generation abandoned', 'AbortError')
      job = await readResponse(await apiFetch(path, { signal }))
      updateVisualProgress(id, job.stage)
    }
    if (job.state !== 'succeeded' || !job.result) {
      const stage = visualStageLabel(job.stage)
      throw new Error(stage ? `${stage} ${job.message}` : job.message)
    }
    return job.result
  } finally {
    clearVisualProgress(id)
    signal?.removeEventListener('abort', cancel)
  }
}
