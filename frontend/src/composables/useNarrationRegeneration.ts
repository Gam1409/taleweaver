import { computed, onScopeDispose, ref } from 'vue'
import type { UseGameSocket } from '@/composables/useGameSocket'
import type { ChatMessage } from '@/types'
import { apiFetch } from '@/services/http'
import { useNotifications } from '@/composables/useNotifications'

/** Replace prose in place; never resend the player's committed action. */
export function useNarrationRegeneration(gameId: () => string | undefined, socket: UseGameSocket) {
  const busy = ref(false)
  let disposed = false
  onScopeDispose(() => { disposed = true })
  const { addNotification } = useNotifications()
  const latest = computed(() => [...socket.messages.value].reverse()
    .find(message => message.role === 'assistant' || message.role === 'user'))
  const canRegenerate = computed(() => Boolean(
    gameId() && latest.value?.role === 'assistant' && latest.value.id && !busy.value &&
    !socket.inputLocked.value && !socket.sheet.value?.agent_active &&
    ['connected', 'completed'].includes(socket.status.value),
  ))

  async function regenerate(): Promise<void> {
    if (!canRegenerate.value || !latest.value) return
    const id = gameId()
    const message = latest.value
    const previousStatus = socket.status.value
    busy.value = true
    socket.status.value = 'loading'
    socket.statusText.value = 'Regenerating response...'
    try {
      const response = await apiFetch(`/adventures/${encodeURIComponent(id!)}/chat/regenerate`, {
        method: 'POST',
        includeJson: true,
        body: JSON.stringify({ message_id: message.id }),
        timeoutMs: null,
      })
      if (!response.ok) {
        const error = await response.json().catch(() => ({}))
        throw new Error(error.detail || 'Could not regenerate the response.')
      }
      const replacement: ChatMessage = await response.json()
      if (replacement.id !== message.id || !replacement.content?.trim()) {
        throw new Error('The server returned an invalid response.')
      }
      if (disposed || gameId() !== id) return
      socket.messages.value = socket.messages.value.map(item => item.id === message.id ? replacement : item)
    } catch (error) {
      if (!disposed && gameId() === id) {
        addNotification(error instanceof Error ? error.message : 'Could not regenerate the response.', 'error')
      }
    } finally {
      busy.value = false
      if (!disposed && gameId() === id && socket.status.value === 'loading') {
        socket.status.value = previousStatus
        socket.statusText.value = ''
      }
    }
  }

  return { regenerate, busy, canRegenerate }
}
