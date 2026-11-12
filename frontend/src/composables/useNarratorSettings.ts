import { computed, onScopeDispose, ref, watch } from 'vue'
import { apiFetch } from '@/services/http'

export interface NarratorVoice {
  id: string
  name: string
  description: string
  instruction: string
  sample: string
}

export interface NarratorSettings {
  voice: NarratorVoice | null
  verbosity: 'default' | 'terse' | 'dialogue' | 'balanced' | 'rich' | 'epic'
  flow: 'off' | 'gentle' | 'balanced'
}

export const VERBOSITY_OPTIONS = [
  ['default', 'Current narration'], ['terse', 'Brief'], ['dialogue', 'Dialogue first'],
  ['balanced', 'Balanced'], ['rich', 'Detailed'], ['epic', 'Expansive'],
] as const

export const FLOW_OPTIONS = [['off', 'Off'], ['gentle', 'Gentle'], ['balanced', 'Balanced']] as const

const empty = (): NarratorSettings => ({ voice: null, verbosity: 'default', flow: 'gentle' })
const normalize = (value: NarratorSettings): NarratorSettings => ({
  ...JSON.parse(JSON.stringify(value)),
  flow: FLOW_OPTIONS.some(([flow]) => flow === value.flow) ? value.flow : 'gentle',
})

export function useNarratorSettings(endpoint: () => string) {
  const settings = ref<NarratorSettings>(empty())
  const voices = ref<NarratorVoice[]>([])
  const loaded = ref(false)
  const busy = ref(false)
  const error = ref('')
  const saved = ref(JSON.stringify(empty()))
  const dirty = computed(() => loaded.value && JSON.stringify(settings.value) !== saved.value)
  let controller: AbortController | null = null

  async function request(method: 'GET' | 'PUT'): Promise<boolean> {
    controller?.abort()
    const current = new AbortController()
    controller = current
    busy.value = true
    error.value = ''
    const path = endpoint()
    try {
      const response = await apiFetch(path, {
        method, signal: current.signal, includeJson: method === 'PUT',
        ...(method === 'PUT' ? { body: JSON.stringify(settings.value) } : {}),
      })
      const body = await response.json()
      if (controller !== current || path !== endpoint()) return false
      if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not save narrator settings.')
      settings.value = normalize(body.settings)
      voices.value = body.voices
      saved.value = JSON.stringify(settings.value)
      loaded.value = true
      return true
    } catch (cause) {
      if (controller !== current || path !== endpoint()) return false
      error.value = cause instanceof Error && cause.name !== 'AbortError'
        ? cause.message : 'Narrator settings request timed out. Please retry.'
      return false
    } finally {
      if (controller === current) busy.value = false
    }
  }

  async function load(): Promise<boolean> {
    loaded.value = false
    return request('GET')
  }

  async function save(): Promise<boolean> {
    if (busy.value) return false
    if (!dirty.value) return true
    return request('PUT')
  }

  function selectVoice(id: string) {
    if (!id) { settings.value.voice = null; return }
    if (id === 'custom') {
      settings.value.voice = { id, name: 'Custom narrator', description: '', instruction: '', sample: '' }
      return
    }
    const voice = voices.value.find(entry => entry.id === id)
    if (voice) settings.value.voice = { ...voice }
  }

  watch(endpoint, () => { settings.value = empty(); void load() }, { immediate: true })
  onScopeDispose(() => { controller?.abort(); controller = null })
  return { settings, voices, loaded, busy, error, dirty, load, save, selectVoice }
}
