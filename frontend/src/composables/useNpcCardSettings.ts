import { computed, onScopeDispose, shallowRef, watch, type Ref } from 'vue'
import { authState } from '@/store/auth'

interface PreferenceState {
  showState: Ref<boolean>
  loaded: Ref<boolean>
  saving: Ref<boolean>
  error: Ref<string>
  revision: number
  consumers: number
  request: AbortController | null
}

const preferences = new Map<string, PreferenceState>()

function createState(): PreferenceState {
  return { showState: shallowRef(false), loaded: shallowRef(false), saving: shallowRef(false), error: shallowRef(''), revision: 0, consumers: 0, request: null }
}

export interface NpcCardSettingsController {
  showState: Readonly<Ref<boolean>>
  loaded: Readonly<Ref<boolean>>
  saving: Readonly<Ref<boolean>>
  error: Readonly<Ref<string>>
  refresh: () => Promise<void>
  setShowState: (enabled: boolean) => Promise<void>
}

/** Session-wide, fail-closed display preference; never a source of NPC knowledge. */
export function useNpcCardSettings(sessionId: Ref<string>): NpcCardSettingsController {
  const active = shallowRef<PreferenceState | null>(null)
  let activeKey = ''

  async function update(enabled?: boolean): Promise<void> {
    const state = active.value
    if (!state || !sessionId.value) return
    state.request?.abort()
    const controller = new AbortController()
    state.request = controller
    const revision = ++state.revision
    const id = sessionId.value
    const token = authState.token
    // Hide immediately on disable, and do not reveal on enable until acknowledged.
    state.showState.value = false
    state.saving.value = true
    state.error.value = ''
    const timeout = setTimeout(() => controller.abort(), 15000)
    try {
      const response = await fetch(`/api/adventures/${encodeURIComponent(id)}/npc-card-settings`, {
        method: enabled === undefined ? 'GET' : 'PATCH',
        headers: { Authorization: `Bearer ${token}`, ...(enabled === undefined ? {} : { 'Content-Type': 'application/json' }) },
        ...(enabled === undefined ? {} : { body: JSON.stringify({ show_state: enabled }) }),
        signal: controller.signal,
      })
      if (!response.ok) throw new Error('Character display settings are unavailable.')
      const data = await response.json() as { show_state?: unknown }
      if (revision !== state.revision) return
      state.showState.value = data.show_state === true
      state.loaded.value = true
    } catch {
      if (revision !== state.revision) return
      state.loaded.value = false
      state.error.value = enabled === undefined
        ? 'Could not load display settings. Indicators remain hidden. Please retry.'
        : 'Could not save display settings. Indicators remain hidden here. Please retry or reload.'
    } finally {
      clearTimeout(timeout)
      if (revision === state.revision) state.saving.value = false
    }
  }

  function release(): void {
    const state = active.value
    if (!state) return
    state.consumers--
    if (state.consumers === 0) {
      state.revision++
      state.request?.abort()
      preferences.delete(activeKey)
    }
    active.value = null
  }

  watch([sessionId, () => authState.token], () => {
    release()
    if (!sessionId.value) return
    activeKey = `${authState.token}:${sessionId.value}`
    const state = preferences.get(activeKey) || createState()
    preferences.set(activeKey, state)
    state.consumers++
    active.value = state
    if (!state.loaded.value && !state.saving.value) void update()
  }, { immediate: true })
  onScopeDispose(release)

  return {
    showState: computed(() => active.value?.showState.value === true),
    loaded: computed(() => active.value?.loaded.value === true),
    saving: computed(() => active.value?.saving.value === true),
    error: computed(() => active.value?.error.value || ''),
    refresh: () => update(),
    setShowState: enabled => update(enabled),
  }
}
