/** Only one background history read at a time; never governs a generation stream. */
export function createSnapshotPoller(read: (signal: AbortSignal) => Promise<void>) {
  let interval: ReturnType<typeof setInterval> | undefined
  let pending: AbortController | null = null

  async function tick(): Promise<void> {
    if (pending) return
    const controller = new AbortController()
    pending = controller
    const deadline = setTimeout(() => controller.abort(), 15_000)
    try {
      await read(controller.signal)
    } finally {
      clearTimeout(deadline)
      if (pending === controller) pending = null
    }
  }

  function interrupt(): void {
    pending?.abort()
  }

  function stop(): void {
    clearInterval(interval)
    interval = undefined
    interrupt()
  }

  function start(): void {
    stop()
    interval = setInterval(() => {
      void tick().catch(error => console.warn('Background history refresh failed:', error))
    }, 5000)
  }

  return { start, stop, interrupt, tick }
}
