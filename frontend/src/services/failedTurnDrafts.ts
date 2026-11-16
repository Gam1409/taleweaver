import type { ChatMessage } from '@/types'

/** A durable pending input can offer a retry after navigation or a page reload. */
export function pendingTurnError(value: unknown, dismissedAction = ''): { message: string; action: string; draft?: string } | null {
  if (!value || typeof value !== 'object') return null
  const pending = value as Record<string, unknown>
  if (typeof pending.action !== 'string' || !pending.action.trim() || pending.action === dismissedAction) return null
  const detail = typeof pending.message === 'string' ? pending.message : 'The previous turn did not finish. Retry the original action.'
  const message = pending.draft_truncated === true ? `${detail} The saved draft was truncated.` : detail
  return { message, action: pending.action, ...(typeof pending.draft === 'string' && pending.draft ? { draft: pending.draft } : {}) }
}

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
