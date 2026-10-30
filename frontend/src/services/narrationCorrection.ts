import { reactive } from 'vue'

export const CORRECTION_MAX_LENGTH = 2000
export const correctionPresets = [
  {
    label: 'Repetitive wording or sounds',
    text: 'Stop repeating phrases, gestures, and sound-tag chains from previous replies. Keep dialogue meaningful and varied. Use vocal tags only sparingly when the current action warrants them; preserve useful emotion labels. Do not carry breathing, laughter, or other temporary reactions into unrelated moments.',
  },
  {
    label: 'Controlling my character',
    text: 'Do not invent speech, decisions, feelings, consent, or voluntary actions for the player character. Narrate the established consequences and other characters, then leave the player room to choose their response.',
  },
  {
    label: 'NPC acting out of character',
    text: 'Keep each NPC consistent with their established personality, knowledge, goals, boundaries, and relationship. Do not make them agree merely to please the player or change their attitude without an established reason. Give characters distinct voices.',
  },
  {
    label: 'Scene or continuity mistake',
    text: 'Recheck the supplied current state and confirmed events. Keep character presence, locations, clothing, object ownership, and chronology consistent. Do not bring an absent character back without an established return, invent possessions, or treat plans and memories as events happening now. Leave unknown details unspecified.',
  },
  {
    label: 'Stalled or padded narration',
    text: 'Stop restating the previous beat, circling the same question, or padding the reply with stock reactions and decorative prose. Address the latest player action directly with a focused response grounded in the confirmed outcome. Allow natural dialogue without forcing a new twist, time jump, or unapproved event.',
  },
] as const

export interface PendingCorrection {
  id: string
  label: string
  text: string
}

const pending = reactive<Record<string, PendingCorrection | null>>({})
const key = (gameId: string) => `taleweaver:narration-correction:${gameId}`

/** Per-session, per-tab feedback survives a reload but never enters story storage. */
export function getCorrection(gameId?: string): PendingCorrection | null {
  if (!gameId) return null
  if (Object.hasOwn(pending, gameId)) return pending[gameId] ?? null
  try {
    const saved = JSON.parse(sessionStorage.getItem(key(gameId)) || 'null')
    pending[gameId] = saved && typeof saved.id === 'string' && typeof saved.label === 'string' &&
      typeof saved.text === 'string' && saved.text.trim() && saved.text.length <= CORRECTION_MAX_LENGTH
      ? saved : null
  } catch {
    // Restricted browser storage falls back to memory for the current tab.
    pending[gameId] = null
  }
  return pending[gameId] ?? null
}

function persist(gameId: string): void {
  try {
    const value = pending[gameId]
    if (value) sessionStorage.setItem(key(gameId), JSON.stringify(value))
    else sessionStorage.removeItem(key(gameId))
  } catch {
    // The reactive in-memory queue remains usable without browser storage.
    return
  }
}

export function queueCorrection(gameId: string, label: string, text: string): void {
  const cleaned = text.trim()
  if (!cleaned || cleaned.length > CORRECTION_MAX_LENGTH) return
  pending[gameId] = { id: `${Date.now()}-${Math.random()}`, label, text: cleaned }
  persist(gameId)
}

export function clearCorrection(gameId: string, expectedId?: string): void {
  if (expectedId && getCorrection(gameId)?.id !== expectedId) return
  pending[gameId] = null
  persist(gameId)
}

/** Only an acknowledged response consumes the captured correction, never a newer edit. */
export function acknowledgeCorrection(gameId: string, sent: PendingCorrection | null, applied: unknown): void {
  if (sent && applied === true) clearCorrection(gameId, sent.id)
}
