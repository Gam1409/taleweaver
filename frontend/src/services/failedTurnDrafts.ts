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

/** A retry may reuse its durable player input, but must save a new reply after it. */
export function savedActionIndex(
  history: ChatMessage[], action: string, knownIds: ReadonlySet<string>, reusableInputId?: string
): number {
  return history.findIndex((message, index) => {
    if (message.role !== 'user' || message.content.trim() !== action || !message.id) return false
    if (!knownIds.has(message.id)) return true
    return message.id === reusableInputId && history.slice(index + 1).some(reply =>
      reply.role === 'assistant' && !!reply.id && !knownIds.has(reply.id)
    )
  })
}
