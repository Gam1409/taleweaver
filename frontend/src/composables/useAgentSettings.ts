import type { Ref } from 'vue'
import type { CharacterSheet } from '@/types'
import { apiFetch, authHeaders } from '@/services/http'

export interface AgentSettingsPatch {
  active?: boolean
  step_by_step?: boolean
  personality?: string
  custom_personality?: string
  allow_walkthrough?: boolean
  monkey_mode?: boolean
}

/** Setting responses belong to one connection, including reconnects to the same ID. */
export function createAgentSettings(
  currentGameId: () => string,
  sheet: Ref<CharacterSheet | null>,
  notify: (message: string, type: 'error') => void,
) {
  const requests = new Set<AbortController>()
  let generation = 0

  function resetAgentSettings() {
    generation++
    requests.forEach(controller => controller.abort())
    requests.clear()
  }

  async function updateAgentSettings(patch: AgentSettingsPatch): Promise<boolean> {
    const gameId = currentGameId()
    if (!gameId) return false
    const controller = new AbortController()
    const requestGeneration = generation
    requests.add(controller)
    const ownsRequest = () => requestGeneration === generation && requests.has(controller) && currentGameId() === gameId && !controller.signal.aborted
    try {
      const res = await apiFetch(`/adventures/${gameId}/agent/settings`, {
        timeoutMs: 60_000, signal: controller.signal, method: 'PATCH',
        headers: authHeaders(true), body: JSON.stringify(patch),
      })
      if (!ownsRequest()) return false
      if (!res.ok) {
        const error = await res.json().catch(() => ({}))
        if (ownsRequest()) notify(error.detail || 'Failed to update Play-Agent settings.', 'error')
        return false
      }
      const agentState = await res.json()
      if (!ownsRequest()) return false
      if (sheet.value) sheet.value = { ...sheet.value, ...agentState }
      return true
    } catch (error) {
      if (ownsRequest()) {
        console.error('[Session] Agent settings error:', error)
        notify('Failed to update Play-Agent settings.', 'error')
      }
      return false
    } finally {
      requests.delete(controller)
    }
  }

  return { updateAgentSettings, resetAgentSettings }
}
