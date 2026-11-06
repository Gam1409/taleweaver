/** Read-only polling: one request, bounded retries, cancellation and explicit pause. */
export interface StatusPollerHandlers<T> {
  onData: (data: T) => boolean
  onPaused: () => void
  onMissing: () => void
}

export function isMissingStatus(error: unknown): boolean {
  return (
    (typeof error === 'object' && error !== null && 'status' in error && error.status === 404) ||
    (error instanceof Error && /^API 404\b/.test(error.message))
  )
}

async function readWithDeadline<T>(
  read: (signal: AbortSignal) => Promise<T>,
  controller: AbortController
): Promise<T> {
  let rejectRead: (error: Error) => void = () => {}
  const aborted = new Promise<never>((_resolve, reject) => {
    rejectRead = reject
  })
  const onAbort = () => rejectRead(new DOMException('Status read stopped', 'AbortError'))
  controller.signal.addEventListener('abort', onAbort, { once: true })
  const deadline = setTimeout(() => controller.abort(), 15_000)
  try {
    return await Promise.race([read(controller.signal), aborted])
  } finally {
    clearTimeout(deadline)
    controller.signal.removeEventListener('abort', onAbort)
  }
}

export function createStatusPoller<T>(
  read: (signal: AbortSignal) => Promise<T>,
  handlers: StatusPollerHandlers<T>
) {
  let timer: ReturnType<typeof setTimeout> | undefined
  let controller: AbortController | null = null
  let pending: Promise<void> | null = null
  let running = false
  let revision = 0
  let failures = 0

  function stop(): void {
    running = false
    revision++
    clearTimeout(timer)
    timer = undefined
    controller?.abort()
  }

  async function attempt(token: number, request: AbortController): Promise<void> {
    try {
      const data = await readWithDeadline(read, request)
      if (token !== revision || request.signal.aborted) return
      failures = 0
      if (!handlers.onData(data)) stop()
    } catch (error) {
      if (token !== revision) return
      if (isMissingStatus(error)) {
        stop()
        handlers.onMissing()
        return
      }
      failures++
      if (failures >= 6) {
        stop()
        handlers.onPaused()
      }
    }
  }

  function checkNow(): Promise<void> {
    if (pending) return pending
    clearTimeout(timer)
    const request = new AbortController()
    const token = revision
    controller = request
    pending = attempt(token, request).finally(() => {
      pending = null
      if (controller === request) controller = null
      if (running && token === revision) {
        const delay = Math.min(1500 * 2 ** failures, 30_000)
        timer = setTimeout(() => {
          void checkNow()
        }, delay)
      }
    })
    return pending
  }

  function start(): Promise<void> {
    if (running) return pending ?? Promise.resolve()
    running = true
    failures = 0
    const token = ++revision
    if (pending)
      return pending.then(() => {
        if (running && token === revision) return checkNow()
      })
    return checkNow()
  }

  const restart = (): Promise<void> => {
    stop()
    return start()
  }
  return { start, stop, checkNow, restart }
}
