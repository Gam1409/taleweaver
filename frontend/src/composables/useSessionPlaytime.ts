import { onMounted, onBeforeUnmount, watch } from 'vue'
import { apiFetch } from '@/services/http'

/** Heartbeats count visible time, including reading and waiting for narration. */
export function useSessionPlaytime(gameId: () => string, ready: () => boolean): void {
  let trackedId: string | null = null
  let timer: ReturnType<typeof setInterval> | undefined
  let pending = Promise.resolve()

  function send(id: string, active: boolean, start = false): void {
    // Keep start/tick/stop requests ordered, including rapid navigation.
    pending = pending.then(async () => {
      try {
        const response = await apiFetch(`/adventures/sessions/${encodeURIComponent(id)}/playtime`, {
          method: 'POST', includeJson: true, keepalive: true,
          body: JSON.stringify({ active, start }), timeoutMs: 10_000,
        })
        if (!response.ok) console.warn('Could not save session playtime:', response.status)
      } catch (error) {
        console.warn('Could not save session playtime:', error)
      }
    })
  }

  function stop(): void {
    if (!trackedId) return
    send(trackedId, false)
    trackedId = null
  }

  function sync(): void {
    const id = gameId()
    const visible = document.visibilityState === 'visible'
    if (trackedId && (trackedId !== id || !visible || !ready())) stop()
    if (trackedId || !id || !visible || !ready()) return
    trackedId = id
    send(id, true, true)
  }

  watch([gameId, ready], sync)
  onMounted(() => {
    sync()
    document.addEventListener('visibilitychange', sync)
    window.addEventListener('pagehide', stop)
    window.addEventListener('pageshow', sync)
    timer = setInterval(() => {
      sync()
      if (trackedId) send(trackedId, true)
    }, 15_000)
  })
  onBeforeUnmount(() => {
    clearInterval(timer)
    document.removeEventListener('visibilitychange', sync)
    window.removeEventListener('pagehide', stop)
    window.removeEventListener('pageshow', sync)
    stop()
  })
}
