import { ref, type Ref } from 'vue'
import { authState } from '@/store/auth'

interface PromptSuggestionsRequest {
  suggestionsLoading: Ref<boolean>
  suggestionsError: Ref<string>
  suggestionsNotice: Ref<string>
  refreshSuggestions: () => Promise<void>
  resetSuggestionsRequest: () => void
}

/** Ideas are a separate request: refreshing must never cancel or submit a game turn. */
export function usePromptSuggestions(
  sessionId: () => string,
  canRefresh: () => boolean,
  suggestions: Ref<string[]>,
): PromptSuggestionsRequest {
  const suggestionsLoading = ref(false)
  const suggestionsError = ref('')
  const suggestionsNotice = ref('')
  let activeController: AbortController | null = null

  function resetSuggestionsRequest(): void {
    activeController?.abort()
    activeController = null
    suggestionsLoading.value = false
    suggestionsError.value = ''
    suggestionsNotice.value = ''
  }

  async function refreshSuggestions(): Promise<void> {
    const gameId = sessionId()
    if (!gameId || suggestionsLoading.value || !canRefresh()) return
    const controller = new AbortController()
    activeController = controller
    suggestionsLoading.value = true
    suggestionsError.value = ''
    suggestionsNotice.value = ''
    let timedOut = false
    // The server allows 90 seconds; leave time to deliver its error response.
    const timeout = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, 95_000)
    try {
      const response = await fetch(`/api/adventures/${encodeURIComponent(gameId)}/suggestions`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${authState.token}` },
        signal: controller.signal,
      })
      if (!response.ok) {
        const messages: Record<number, string> = {
          401: 'Your login has expired. Sign in again to refresh ideas.',
          404: 'This session could not be found. Reopen it from your saved sessions.',
          409: 'The scene changed while generating ideas. Please refresh again.',
          502: 'The Small / Utility model could not generate valid ideas. Check its model and connection, then retry.',
          504: 'Generating ideas timed out. Check the Small / Utility model and retry.',
        }
        throw new Error(messages[response.status] || 'Could not refresh ideas. Please try again.')
      }
      const data: { suggestions?: unknown } = await response.json()
      if (!Array.isArray(data.suggestions) || !data.suggestions.length ||
          !data.suggestions.every(value => typeof value === 'string' && value.trim())) {
        throw new Error('The server returned no usable ideas. Please try again.')
      }
      if (activeController !== controller || sessionId() !== gameId) return
      const updated = (data.suggestions as string[]).slice(0, 5)
      const unchanged = updated.length === suggestions.value.length &&
        updated.every(value => suggestions.value.includes(value))
      suggestions.value = updated
      suggestionsNotice.value = unchanged
        ? 'The model returned the same ideas. You can retry or continue playing.'
        : 'Ideas updated.'
    } catch (error) {
      if (activeController !== controller || sessionId() !== gameId) return
      suggestionsError.value = timedOut
        ? 'Generating ideas timed out. Check the Small / Utility model and retry.'
        : error instanceof TypeError ? 'Could not connect to the server. Please try again.'
        : error instanceof Error ? error.message : 'Could not refresh ideas. Please try again.'
    } finally {
      clearTimeout(timeout)
      if (activeController === controller) {
        activeController = null
        suggestionsLoading.value = false
      }
    }
  }

  return { suggestionsLoading, suggestionsError, suggestionsNotice, refreshSuggestions, resetSuggestionsRequest }
}
