/** Keep display-only debug toggles out of story rewrite/replay selection. */
export function isStoryMessage(message: { role: string; content: string; is_debug?: boolean }): boolean {
  if (message.is_debug || !['user', 'assistant'].includes(message.role)) return false
  const toggle = message.content.startsWith('/debug ') &&
    ['on', 'off', 'log on', 'log off'].includes(message.content.slice(7).trim().toLowerCase())
  return message.role !== 'user' || !toggle
}
