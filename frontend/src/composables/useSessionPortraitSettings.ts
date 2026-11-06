import { computed, onScopeDispose, ref, watch } from 'vue'
import { apiFetch } from '@/services/http'

import { DEFAULT_PORTRAIT_PREFERENCES, parsePortraitPreferences, type PortraitPreferences } from '@/utils/npcPresentation'

/** Keep preferences local until Save; abort stale requests when changing sessions. */
export function useSessionPortraitSettings(sessionId: () => string) {
  const draft = ref<PortraitPreferences>({ ...DEFAULT_PORTRAIT_PREFERENCES })
  const saved = ref<PortraitPreferences | null>(null)
  const busy = ref(false)
  const error = ref('')
  const loaded = computed(() => saved.value !== null)
  const dirty = computed(() => loaded.value && (
    JSON.stringify(draft.value) !== JSON.stringify(saved.value)
  ))
  let controller: AbortController | null = null

  async function request(saving: boolean): Promise<boolean> {
    controller?.abort()
    const current = new AbortController()
    controller = current
    busy.value = true
    error.value = ''
    const body = saving ? { settings: { ...draft.value }, expected: { ...saved.value! } } : undefined
    try {
      const response = await apiFetch(`/adventures/${encodeURIComponent(sessionId())}/portrait-settings`, {
        method: saving ? 'PATCH' : 'GET',
        signal: current.signal,
        timeoutMs: 15000,
        ...(body ? { includeJson: true, body: JSON.stringify(body) } : {}),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Could not update portrait settings.')
      const preferences = parsePortraitPreferences(data)
      if (controller !== current) return false
      draft.value = { ...preferences }
      saved.value = { ...preferences }
      return true
    } catch (cause) {
      if (controller === current) error.value = cause instanceof Error ? cause.message : 'Could not update portrait settings.'
      return false
    } finally {
      if (controller === current) busy.value = false
    }
  }

  async function load(): Promise<boolean> {
    saved.value = null
    return request(false)
  }

  async function save(): Promise<boolean> {
    if (busy.value) return false
    if (!loaded.value || !dirty.value) return true
    return request(true)
  }

  watch(sessionId, () => { void load() }, { immediate: true })
  onScopeDispose(() => { controller?.abort(); controller = null })
  return { draft, loaded, dirty, busy, error, load, save }
}
