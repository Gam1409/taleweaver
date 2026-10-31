import type { ChatMessage } from '@/types'

/** Track only local output from a failed request, never persisted story history. */
export function createFailedTurnDrafts() {
  let failed: { action: string; messages: Set<ChatMessage> } | null = null

  return {
    prepare(history: ChatMessage[], action: string) {
      const retry = failed?.action === action
      const messages = history.filter(message =>
        message.id || message.role === 'user' || !failed?.messages.has(message)
      )
      const reusePlayer = retry && messages.some(message =>
        !message.id && message.role === 'user' && message.content === action
      )
      failed = null
      return { messages, retry, reusePlayer }
    },
    record(action: string, history: ChatMessage[], before: Set<ChatMessage>) {
      failed = { action, messages: new Set(history.filter(message => !before.has(message))) }
    },
    clear() {
      failed = null
    }
  }
}
