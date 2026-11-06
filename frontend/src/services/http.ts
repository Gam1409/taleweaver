import { authState } from '@/store/auth'

export const API_BASE = '/api'
const DEFAULT_API_TIMEOUT_MS = 15000

export function authHeaders(includeJson = false): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    'X-Requested-With': 'XMLHttpRequest',
  }
  if (includeJson) {
    headers['Content-Type'] = 'application/json'
  }
  if (authState.token) {
    headers.Authorization = `Bearer ${authState.token}`
  }
  return headers
}

export interface ApiFetchInit extends RequestInit {
  timeoutMs?: number | null
  includeJson?: boolean
}

export function buildApiUrl(path: string): string {
  return path.startsWith('/') ? `${API_BASE}${path}` : `${API_BASE}/${path}`
}

export async function apiFetch(path: string, init: ApiFetchInit = {}): Promise<Response> {
  const {
    timeoutMs = DEFAULT_API_TIMEOUT_MS,
    includeJson = false,
    headers: incomingHeaders,
    signal,
    cache,
    ...rest
  } = init

  const mergedHeaders = new Headers(authHeaders(includeJson))
  const callerHeaders = new Headers(incomingHeaders)
  callerHeaders.forEach((value, key) => mergedHeaders.set(key, value))

  async function send(requestSignal?: AbortSignal | null): Promise<Response> {
    const response = await fetch(buildApiUrl(path), {
      ...rest,
      headers: mergedHeaders,
      signal: requestSignal,
      credentials: 'same-origin',
      cache: cache ?? 'no-store',
    })
    if (response.status === 401) window.dispatchEvent(new Event('auth-unauthorized'))
    return response
  }

  // Long model calls and streaming retain their native body and caller deadline.
  if (timeoutMs === null) return send(signal)
  if (signal?.aborted) throw new DOMException('Request aborted.', 'AbortError')
  const controller = new AbortController()
  let rejectPending: (reason: DOMException) => void
  const canceled = new Promise<never>((_, reject) => { rejectPending = reject })
  const abort = () => {
    controller.abort(signal?.reason)
    rejectPending(new DOMException('Request aborted.', 'AbortError'))
  }
  signal?.addEventListener('abort', abort, { once: true })
  const timeoutId = window.setTimeout(() => {
    controller.abort('request-timeout')
    rejectPending(new DOMException('Request timed out.', 'AbortError'))
  }, timeoutMs)
  try {
    const complete = async () => {
      const response = await send(controller.signal)
      if (!response.body) return response
      const bytes = await response.arrayBuffer()
      const buffered = new Response(bytes, {
        status: response.status, statusText: response.statusText, headers: response.headers,
      })
      // Finite requests complete under one deadline, including the response body.
      for (const key of ['url', 'redirected', 'type'] as const) {
        Object.defineProperty(buffered, key, { value: response[key] })
      }
      return buffered
    }
    return await Promise.race([complete(), canceled])
  } finally {
    clearTimeout(timeoutId)
    signal?.removeEventListener('abort', abort)
  }
}
