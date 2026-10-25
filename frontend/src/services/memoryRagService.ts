import { apiFetch } from '@/services/http'

export interface MemoryRagSettings {
  enabled: boolean
  provider: 'openai' | 'ollama'
  base_url: string
  model: string
  timeout_seconds: number
  key_configured?: boolean
}

export interface MemoryRagPayload extends Omit<MemoryRagSettings, 'key_configured'> {
  api_key?: string
}

export interface MemoryIndexStatus {
  enabled: boolean
  status: string
  session_count: number
  pending_count: number
  indexed_count?: number
  paused: boolean
}

export function memoryRagPayload(settings: MemoryRagSettings, apiKey: string): MemoryRagPayload {
  return {
    enabled: settings.enabled,
    provider: settings.provider,
    base_url: settings.base_url.trim(),
    model: settings.model.trim(),
    timeout_seconds: settings.timeout_seconds,
    ...(apiKey.trim() ? { api_key: apiKey.trim() } : {})
  }
}

async function request<T>(path: string, method = 'GET', payload?: MemoryRagPayload): Promise<T> {
  const response = await apiFetch(path, {
    method,
    includeJson: true,
    body: payload ? JSON.stringify(payload) : undefined,
    timeoutMs: payload ? (payload.timeout_seconds + 10) * 1000 : 20000
  })
  if (!response.ok) {
    // Avoid displaying upstream responses that might contain provider credentials.
    const message =
      response.status === 403
        ? 'You do not have permission to manage this memory index.'
        : 'The request failed. Check your embeddings settings and try again.'
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

function indexPath(templateId: string): string {
  return `/adventures/templates/${encodeURIComponent(templateId)}/memory-index`
}

export const memoryRagService = {
  getSettings(): Promise<MemoryRagSettings> {
    return request('/settings/memory-rag')
  },
  saveSettings(payload: MemoryRagPayload): Promise<MemoryRagSettings> {
    return request('/settings/memory-rag', 'PUT', payload)
  },
  testSettings(
    payload: MemoryRagPayload
  ): Promise<{ ok: boolean; message: string; dimensions?: number }> {
    return request('/settings/memory-rag/test', 'POST', payload)
  },
  getIndex(templateId: string): Promise<MemoryIndexStatus> {
    return request(indexPath(templateId))
  },
  clearIndex(
    templateId: string
  ): Promise<{ cleared: boolean; session_count: number; paused: boolean }> {
    return request(indexPath(templateId), 'DELETE')
  },
  rebuildIndex(templateId: string): Promise<{ queued: boolean; session_count: number }> {
    return request(`${indexPath(templateId)}/rebuild`, 'POST')
  }
}
