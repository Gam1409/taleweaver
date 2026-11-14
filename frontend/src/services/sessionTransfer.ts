/** ADS transfers keep a finite deadline through upload, headers and native body consumption. */
export const SESSION_TRANSFER_TIMEOUT_MS = 60 * 60 * 1000

export async function withSessionTransferDeadline<T>(
  transfer: (signal: AbortSignal) => Promise<T>,
  parent?: AbortSignal,
): Promise<T> {
  if (parent?.aborted) throw new DOMException('Session transfer cancelled.', 'AbortError')
  const controller = new AbortController()
  let timedOut = false
  let rejectTransfer: (reason: DOMException) => void = () => {}
  const interrupted = new Promise<never>((_resolve, reject) => { rejectTransfer = reject })
  const onAbort = () => rejectTransfer(new DOMException(
    timedOut ? 'Session transfer timed out.' : 'Session transfer cancelled.', 'AbortError',
  ))
  const onParentAbort = () => controller.abort(parent?.reason)
  controller.signal.addEventListener('abort', onAbort, { once: true })
  parent?.addEventListener('abort', onParentAbort, { once: true })
  const timer = window.setTimeout(() => {
    timedOut = true
    controller.abort('session-transfer-timeout')
  }, SESSION_TRANSFER_TIMEOUT_MS)
  try {
    return await Promise.race([transfer(controller.signal), interrupted])
  } finally {
    window.clearTimeout(timer)
    parent?.removeEventListener('abort', onParentAbort)
    controller.signal.removeEventListener('abort', onAbort)
  }
}
