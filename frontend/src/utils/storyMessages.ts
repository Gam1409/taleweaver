/** Separate story prose, Debug visibility and state-changing replay boundaries. */
interface TranscriptMessage {
  role: string
  content: string
  is_debug?: boolean
}

function isDebugCommand(message: TranscriptMessage): boolean {
  return message.role === 'user' && message.content.trimStart().toLowerCase().startsWith('/debug')
}

function isDebugMessage(message: TranscriptMessage): boolean {
  return Boolean(
    message.is_debug ||
    isDebugCommand(message) ||
    (message.role === 'system' && /^(\[DEBUG|DEBUG:|--- DEBUG)/i.test(message.content.trimStart()))
  )
}

export function visibleChatMessages<T extends TranscriptMessage>(
  messages: T[],
  showDebug: boolean
): T[] {
  if (showDebug) return messages
  let debugCommand = false
  return messages.filter(message => {
    const marked = isDebugMessage(message)
    if (message.role === 'user') debugCommand = marked
    else if (message.role === 'system') {
      const pending = debugCommand
      debugCommand = false
      return !marked && !pending
    } else if (message.role === 'assistant') debugCommand = false
    return !marked
  })
}

/** Hidden world edits still separate a previous narration from the current state. */
export function isReplayBoundary(message: TranscriptMessage): boolean {
  const toggle =
    message.content.startsWith('/debug ') &&
    ['on', 'off', 'log on', 'log off'].includes(message.content.slice(7).trim().toLowerCase())
  return (
    isStoryMessage(message) ||
    ((isDebugCommand(message) || (message.role === 'user' && Boolean(message.is_debug))) &&
      !toggle) ||
    (message.role === 'assistant' && Boolean(message.is_debug))
  )
}

export function isStoryMessage(message: {
  role: string
  content: string
  is_debug?: boolean
}): boolean {
  return !isDebugMessage(message) && ['user', 'assistant'].includes(message.role)
}
