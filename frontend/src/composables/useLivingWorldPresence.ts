import { onMounted, onBeforeUnmount, watch } from 'vue'
import { createPresenceId, livingWorldRequest, type LivingWorldStatus } from '@/services/livingWorld'

/** Heartbeats trigger optional server-side batches without waiting for inference. */
export function useLivingWorldPresence(gameId: () => string, ready: () => boolean): void {
  const clientId = createPresenceId()
  let tracked: string | null = null
  let disposed = false
  let pending = Promise.resolve()
  let timer: ReturnType<typeof setInterval> | undefined

  function enqueue(): void {
    const id = !disposed && !document.hidden && ready() ? gameId() : null
    pending = pending.then(async () => {
      try {
        if (tracked && tracked !== id) {
          await livingWorldRequest(tracked, '/presence', 'POST', { client_id: clientId, active: false })
          tracked = null
        }
        if (!id) return
        const first = tracked !== id
        const status = await livingWorldRequest<LivingWorldStatus>(id)
        if (!status.settings.living_world_enabled) { tracked = null; return }
        await livingWorldRequest(id, '/presence', 'POST', { client_id: clientId, active: true })
        tracked = id
        if (first && !disposed && gameId() === id && ready() && status.settings.auto_catchup_on_resume && !status.settings.live_enabled) {
          const current = await livingWorldRequest<LivingWorldStatus>(id)
          // Keep presence heartbeats flowing while the bounded model batch runs.
          void livingWorldRequest(id, current.settings.deliberation_enabled ? '/cycle' : '/resume', 'POST', { expected_revision: current.revision })
            .catch(cause => console.warn('Living World batch could not complete:', cause))
        }
      } catch (cause) { console.warn('Living World presence could not be updated:', cause) }
    })
  }

  function leaving(): void { disposed = true; enqueue() }
  function returning(): void { disposed = false; enqueue() }
  watch([gameId, ready], enqueue)
  onMounted(() => {
    enqueue()
    document.addEventListener('visibilitychange', enqueue)
    window.addEventListener('pagehide', leaving)
    window.addEventListener('pageshow', returning)
    window.addEventListener('living-world-settings-changed', enqueue)
    timer = setInterval(enqueue, 20_000)
  })
  onBeforeUnmount(() => {
    clearInterval(timer)
    document.removeEventListener('visibilitychange', enqueue)
    window.removeEventListener('pagehide', leaving)
    window.removeEventListener('pageshow', returning)
    window.removeEventListener('living-world-settings-changed', enqueue)
    leaving()
  })
}
