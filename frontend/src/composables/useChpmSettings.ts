import { computed, onScopeDispose, ref, watch } from 'vue'
import { apiFetch } from '@/services/http'

export interface ChpmSettings {
  mode: 'off' | 'shadow' | 'live'
  actor_ids: string[]
  model_role: 'small' | 'complex'
  max_output_tokens: number
  max_input_chars: number
  max_calls_per_turn: number
  memory_limit: number
}

export interface ChpmStatus {
  settings: ChpmSettings
  revision: number
  available: boolean
  characters: { id: string; name: string }[]
  usage: { calls: number; input_chars: number; output_chars: number; repairs: number; status: string; detail: string; memory_evictions: number }
  trace: unknown[]
  memory_counts: Record<string, number>
  memory: Record<string, unknown[]>
}

export function useChpmSettings(sessionId: () => string) {
  const status = ref<ChpmStatus | null>(null)
  const draft = ref<ChpmSettings | null>(null)
  const busy = ref(false)
  const error = ref('')
  const dirty = computed(() => !!status.value && JSON.stringify(draft.value) !== JSON.stringify(status.value.settings))
  let controller: AbortController | null = null

  async function request(saving: boolean): Promise<boolean> {
    controller?.abort()
    const current = new AbortController()
    controller = current
    busy.value = true
    error.value = ''
    try {
      const response = await apiFetch(`/adventures/${encodeURIComponent(sessionId())}/chpm`, {
        method: saving ? 'PATCH' : 'GET', signal: current.signal, timeoutMs: 15000,
        ...(saving ? { includeJson: true, body: JSON.stringify({ settings: draft.value, expected_revision: status.value?.revision }) } : {}),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : 'Could not save NPC behavior settings.')
      if (controller !== current) return false
      status.value = data as ChpmStatus
      draft.value = { ...data.settings, actor_ids: [...data.settings.actor_ids] }
      return true
    } catch (cause) {
      if (controller === current) error.value = cause instanceof Error ? cause.message : 'Could not load NPC behavior settings.'
      return false
    } finally {
      if (controller === current) busy.value = false
    }
  }

  async function load(): Promise<boolean> {
    status.value = null
    draft.value = null
    return request(false)
  }

  async function save(): Promise<boolean> {
    if (busy.value) return false
    if (!status.value || !dirty.value) return true
    return request(true)
  }

  watch(sessionId, () => { void load() }, { immediate: true })
  onScopeDispose(() => { controller?.abort(); controller = null })
  return { status, draft, busy, error, dirty, load, save }
}
