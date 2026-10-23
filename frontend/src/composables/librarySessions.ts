import type { GameSession } from '@/types'

export type LibrarySessions = ReadonlyMap<string, GameSession>

function sessionPriority(session: GameSession): number {
  return !session.status || session.status === 'active' || session.status === 'paused' ? 1 : 0
}

function createdAt(session: GameSession): number {
  const timestamp = Date.parse(session.created_at || '')
  return Number.isFinite(timestamp) ? timestamp : 0
}

/** Prefer the newest active save; completed games can still be opened as in Sessions. */
export function indexLibrarySessions(sessions: readonly GameSession[]): LibrarySessions {
  const result = new Map<string, GameSession>()
  for (const session of sessions) {
    const templateId = session.template_id || session.adventure_id
    if (!templateId || !session.game_id || session.status === 'archived') continue
    const previous = result.get(templateId)
    const priority = previous ? sessionPriority(session) - sessionPriority(previous) : 1
    if (priority > 0 || (priority === 0 && createdAt(session) > createdAt(previous!))) {
      result.set(templateId, session)
    }
  }
  return result
}
