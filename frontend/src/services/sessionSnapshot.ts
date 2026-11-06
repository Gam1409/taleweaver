import { apiFetch } from './http'

export class SessionSnapshotError extends Error {}

const unavailable = 'The session could not be loaded. Check the backend connection and try again.'

function statusMessage(status: number): string {
  if (status === 404) return 'This session could not be found. Return to the library or try again.'
  if (status === 401) return 'Sign in again to load this session.'
  if (status === 403) return 'You do not have access to this session.'
  return unavailable
}

export function snapshotErrorMessage(error: unknown): string {
  return error instanceof SessionSnapshotError ? error.message : unavailable
}

async function read(gameId: string, signal: AbortSignal): Promise<Record<string, unknown>> {
  const response = await apiFetch(`/adventures/${encodeURIComponent(gameId)}/chat`, {
    signal,
    timeoutMs: null
  })
  if (!response.ok) throw new SessionSnapshotError(statusMessage(response.status))
  const data: unknown = await response.json()
  if (!data || typeof data !== 'object' || !('messages' in data) || !Array.isArray(data.messages)) {
    throw new SessionSnapshotError(
      'The server returned unreadable session data. Try again or check the server logs.'
    )
  }
  return data as Record<string, unknown>
}

/** The read-only deadline includes both HTTP headers and the entire JSON body. */
export async function readSessionSnapshot(
  gameId: string,
  parent?: AbortSignal
): Promise<Record<string, unknown>> {
  if (parent?.aborted) throw new DOMException('Session load cancelled', 'AbortError')
  const controller = new AbortController()
  let timedOut = false
  let rejectRead: (reason: Error) => void = () => {}
  const interrupted = new Promise<never>((_resolve, reject) => {
    rejectRead = reject
  })
  const onAbort = () =>
    rejectRead(
      timedOut
        ? new SessionSnapshotError(
            'Loading the session timed out. Check the backend connection and try again.'
          )
        : new DOMException('Session load cancelled', 'AbortError')
    )
  const onParentAbort = () => controller.abort()
  controller.signal.addEventListener('abort', onAbort, { once: true })
  parent?.addEventListener('abort', onParentAbort, { once: true })
  const timer = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, 15_000)
  try {
    return await Promise.race([read(gameId, controller.signal), interrupted])
  } catch (error) {
    if (
      error instanceof SessionSnapshotError ||
      (error instanceof Error && error.name === 'AbortError')
    )
      throw error
    throw new SessionSnapshotError(unavailable)
  } finally {
    window.clearTimeout(timer)
    parent?.removeEventListener('abort', onParentAbort)
    controller.signal.removeEventListener('abort', onAbort)
  }
}
