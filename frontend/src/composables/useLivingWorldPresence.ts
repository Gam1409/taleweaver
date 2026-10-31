import { onMounted, onBeforeUnmount, watch } from 'vue'
import { createPresenceId, livingWorldRequest, type LivingWorldStatus } from '@/services/livingWorld'

/** Heartbeats trigger optional server-side batches without waiting for inference. */
export function useLivingWorldPresence(gameId: () => string, ready: () => boolean): void {
  const clientId = createPresenceId()
  let tracked: string | null = null
  let disposed = false
  let running = false
  let requested = false
  let generation = 0
  let timer: ReturnType<typeof setInterval> | undefined

  function currentId(): string | null {
    return !disposed && !document.hidden && ready() ? gameId() : null
  }

  async function update(version: number): Promise<void> {
    const id = currentId()
    if (tracked && tracked !== id) {
      await livingWorldRequest(tracked, '/presence', 'POST', { client_id: clientId, active: false })
      tracked = null
    }
    const current = () => generation === version && currentId() === id
    if (!id || !current()) return
    const first = tracked !== id
    const status = await livingWorldRequest<LivingWorldStatus>(id)
    if (!current()) return
    if (!status.settings.living_world_enabled) { tracked = null; return }
    await livingWorldRequest(id, '/presence', 'POST', { client_id: clientId, active: true })
    tracked = id
    if (!current()) return
    if (first && status.settings.auto_catchup_on_resume && !status.settings.live_enabled) {
      const latest = await livingWorldRequest<LivingWorldStatus>(id)
      if (!current() || !latest.settings.living_world_enabled || !latest.settings.auto_catchup_on_resume || latest.settings.live_enabled) return
      // Presence remains independent of the bounded model batch.
      void livingWorldRequest(id, latest.settings.deliberation_enabled ? '/cycle' : '/resume', 'POST', { expected_revision: latest.revision })
        .catch(cause => console.warn('Living World batch could not complete:', cause))
    }
  }

  async function drain(): Promise<void> {
    running = true
    try {
      while (requested) {
        requested = false
        try { await update(generation) }
        catch (cause) { console.warn('Living World presence could not be updated:', cause) }
      }
    } finally { running = false }
  }

  function enqueue(): void {
    generation++
    requested = true
    if (!running) void drain()
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
