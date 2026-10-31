import { onMounted, onBeforeUnmount, watch } from 'vue'
import { createPresenceId, livingWorldRequest, type LivingWorldStatus } from '@/services/livingWorld'

/** Presence is independent of inference and never advances the world by itself. */
export function useLivingWorldPresence(gameId: () => string, ready: () => boolean): void {
  const clientId = createPresenceId()
  let tracked: string | null = null
  let disposed = false
  let pending = Promise.resolve()
  let timer: ReturnType<typeof setInterval> | undefined

  function enqueue(): void {
    const id = !disposed && ready() ? gameId() : null
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
        if (first && !disposed && gameId() === id && ready() && status.settings.auto_catchup_on_resume) {
          const current = await livingWorldRequest<LivingWorldStatus>(id)
          await livingWorldRequest(id, '/resume', 'POST', { expected_revision: current.revision })
        }
      } catch (cause) { console.warn('Living World presence could not be updated:', cause) }
    })
  }

  function leaving(): void { disposed = true; enqueue() }
  function returning(): void { disposed = false; enqueue() }
  watch([gameId, ready], enqueue)
  onMounted(() => {
    enqueue()
    window.addEventListener('pagehide', leaving)
    window.addEventListener('pageshow', returning)
    window.addEventListener('living-world-settings-changed', enqueue)
    timer = setInterval(enqueue, 20_000)
  })
  onBeforeUnmount(() => {
    clearInterval(timer)
    window.removeEventListener('pagehide', leaving)
    window.removeEventListener('pageshow', returning)
    window.removeEventListener('living-world-settings-changed', enqueue)
    leaving()
  })
}
