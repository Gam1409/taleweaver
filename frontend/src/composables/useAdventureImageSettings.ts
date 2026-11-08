import { onScopeDispose, ref, watch } from 'vue'
import { apiFetch } from '@/services/http'
import type { PresetAssignment } from '@/services/imagePurposes'

interface ImageSettings {
  source: 'saved' | 'current'
  selection: Partial<Record<PresetAssignment, string>>
  effective?: {
    provider?: string
    preset_name?: string
    workflow_name?: string
    variant?: string
    error?: string
    models?: { node: string; loader: string; input: string; file: string; folder: string }[]
  }
}
interface Context {
  adventureId: string
  targetType: string
  advanced: boolean
  reference: boolean
}

export function useAdventureImageSettings(context: () => Context, busyChanged: (value: boolean) => void) {
  const data = ref<ImageSettings | null>(null)
  const source = ref<'saved' | 'current'>('current')
  const busy = ref(false)
  const error = ref('')
  const saved = ref(false)
  let revision = 0
  let controller: AbortController | null = null

  function invalidate() {
    revision++
    controller?.abort()
    controller = null
    busy.value = false
    busyChanged(false)
  }
  async function request(save = false) {
    const input = context()
    if (save && (!data.value || busy.value)) return
    invalidate()
    const current = revision
    controller = new AbortController()
    const signal = controller.signal
    const endpoint = `/adventures/${encodeURIComponent(input.adventureId)}/visual-presets`
    const purpose = input.targetType === 'scene' ? 'background' : input.targetType
    const query = new URLSearchParams({ purpose, advanced: String(input.advanced), reference: String(input.reference) })
    busy.value = true
    busyChanged(true)
    error.value = ''
    saved.value = false
    try {
      if (save) {
        const response = await apiFetch(endpoint, {
          method: 'PUT', includeJson: true, signal,
          body: JSON.stringify({ source: source.value }),
        })
        if (!response.ok) {
          const result = await response.json().catch(() => ({}))
          throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not save adventure image settings.')
        }
      }
      const response = await apiFetch(`${endpoint}?${query}`, { signal })
      if (!response.ok) throw new Error('Could not load adventure image settings. Please retry.')
      const result: ImageSettings = await response.json()
      if (current !== revision) return
      data.value = result
      source.value = result.source
      saved.value = save
    } catch (cause) {
      if (current === revision && !signal.aborted) error.value = cause instanceof Error ? cause.message : 'Could not load image settings.'
    } finally {
      if (current === revision) {
        busy.value = false
        busyChanged(false)
      }
    }
  }
  watch(() => JSON.stringify(context()), () => {
    data.value = null
    void request()
  }, { immediate: true, flush: 'sync' })
  onScopeDispose(invalidate)
  return { data, source, busy, error, saved, reload: () => request(), save: () => request(true) }
}
