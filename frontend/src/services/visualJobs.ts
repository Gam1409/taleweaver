import { apiFetch } from '@/services/http'

interface JobStatus {
  id: string
  state: 'queued' | 'running' | 'succeeded' | 'failed' | 'abandoned'
  message: string
  result: Record<string, unknown> | null
}

async function readResponse(response: Response): Promise<JobStatus> {
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Invalid image job request.')
  return data as JobStatus
}

export async function runVisualJob(
  operation: 'test' | 'asset' | 'catalog' | 'avatar',
  payload: unknown,
  templateId?: string,
  signal?: AbortSignal,
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
      body: JSON.stringify({ id, operation, template_id: templateId, payload }),
    }))
    while (job.state === 'queued' || job.state === 'running') {
      await new Promise(resolve => window.setTimeout(resolve, 1000))
      if (signal?.aborted) throw new DOMException('Generation abandoned', 'AbortError')
      job = await readResponse(await apiFetch(path, { signal }))
    }
    if (job.state !== 'succeeded' || !job.result) throw new Error(job.message)
    return job.result
  } finally {
    signal?.removeEventListener('abort', cancel)
  }
}
