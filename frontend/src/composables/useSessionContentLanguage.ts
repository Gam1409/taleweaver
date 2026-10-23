import { ref, watch, type Ref } from 'vue'
import { authState } from '@/store/auth'
import { useNotifications } from '@/composables/useNotifications'

interface SessionContentLanguage {
  language: Ref<string>
  languageSaving: Ref<boolean>
  setLanguage: (value: string) => Promise<boolean>
}

/** Server-owned session language; local storage only mirrors it for audio playback. */
export function useSessionContentLanguage(
  sessionId: () => string,
  canChange: () => boolean,
  updateSuggestions: (suggestions: string[]) => void,
): SessionContentLanguage {
  const language = ref('')
  const languageSaving = ref(false)
  const { addNotification } = useNotifications()

  watch(language, value => {
    localStorage.setItem('tw_bable_fish_lang', value)
  })

  async function setLanguage(value: string): Promise<boolean> {
    const gameId = sessionId()
    if (!gameId || languageSaving.value || !canChange()) return false
    languageSaving.value = true
    try {
      const response = await fetch(`/api/adventures/${gameId}/content-language`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${authState.token}`,
        },
        body: JSON.stringify({ language: value }),
        signal: AbortSignal.timeout(15_000),
      })
      if (!response.ok) throw new Error('Could not save the game language. Please try again.')
      const result: { language: string; prompt_suggestions: string[] } = await response.json()
      if (sessionId() !== gameId) return false
      language.value = result.language
      updateSuggestions(result.prompt_suggestions)
      return true
    } catch {
      if (sessionId() === gameId) {
        addNotification('Could not save the game language. Your previous choice is still active.', 'error')
      }
      return false
    } finally {
      languageSaving.value = false
    }
  }

  return { language, languageSaving, setLanguage }
}
