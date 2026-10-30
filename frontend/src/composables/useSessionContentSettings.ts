import { computed, onScopeDispose, ref, watch } from 'vue'
import { apiFetch } from '@/services/http'

export interface ContentPreferences {
  enabled: boolean
  level: 'soft' | 'medium' | 'hard'
}

function parsePreferences(data: unknown): ContentPreferences {
  const value = data as Record<string, unknown> | null
  if (typeof value?.enabled !== 'boolean' || typeof value.level !== 'string' || !['soft', 'medium', 'hard'].includes(value.level)) {
    throw new Error('The server returned invalid content settings.')
  }
  return { enabled: value.enabled, level: value.level as ContentPreferences['level'] }
}

/** Keep preferences local until Save; abort stale requests when changing sessions. */
export function useSessionContentSettings(sessionId: () => string) {
  const draft = ref<ContentPreferences>({ enabled: false, level: 'soft' })
  const saved = ref<ContentPreferences | null>(null)
  const busy = ref(false)
  const error = ref('')
  const loaded = computed(() => saved.value !== null)
  const dirty = computed(() => loaded.value && (
    draft.value.enabled !== saved.value?.enabled || draft.value.level !== saved.value?.level
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
      const response = await apiFetch(`/adventures/${encodeURIComponent(sessionId())}/content-settings`, {
        method: saving ? 'PATCH' : 'GET',
        signal: current.signal,
        timeoutMs: 15000,
        ...(body ? { includeJson: true, body: JSON.stringify(body) } : {}),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Could not update content settings.')
      const preferences = parsePreferences(data)
      if (controller !== current) return false
      draft.value = { ...preferences }
      saved.value = { ...preferences }
      return true
    } catch (cause) {
      if (controller === current) error.value = cause instanceof Error ? cause.message : 'Could not update content settings.'
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
