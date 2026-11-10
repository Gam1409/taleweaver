import { computed, shallowRef } from 'vue'

export interface NpcBehaviorStatus {
  module_version: string
  mode: 'off' | 'shadow' | 'live'
  quality: 'idle' | 'verified' | 'partial' | 'simplified'
  reason: string
  cooldown_remaining: number
  unreviewed_turns: number
  total_simplified_turns: number
}

const RECOVERY_REASONS: Record<string, string> = {
  analysis_failed: 'NPC analysis could not be completed.',
  review_unavailable: 'The reply check could not be completed.',
  review_rejected: 'The reply failed character checks; no validated repair was available.',
  narration_incomplete: 'The narrator response was incomplete.',
  cooldown: 'Analysis is paused after repeated failures.',
}

export function npcBehaviorExplanation(state: NpcBehaviorStatus | null): string {
  if (state?.quality === 'partial') return 'Some NPCs have no confirmed decision and remain inactive for this turn. ' +
    'Other NPC updates passed the shared reply check. See NPC Personality settings for the paused characters.'
  if (state?.quality !== 'simplified') return 'Optional NPC character and memory guidance is enabled.'
  const reason = Object.prototype.hasOwnProperty.call(RECOVERY_REASONS, state.reason)
    ? RECOVERY_REASONS[state.reason] + ' '
    : ''
  return reason + 'The story continues with the last confirmed character identity. ' +
    'New psychological updates were not confirmed for this turn. See Diagnostics for the failing request or phase.'
}

const current = shallowRef<{ sessionId: string; value: NpcBehaviorStatus | null }>({
  sessionId: '',
  value: null
})

export function updateNpcBehaviorStatus(sessionId: string, value: unknown): void {
  const valid =
    value !== null &&
    typeof value === 'object' &&
    'module_version' in value &&
    typeof value.module_version === 'string' &&
    'mode' in value &&
    ['off', 'shadow', 'live'].includes(String(value.mode)) &&
    'quality' in value &&
    ['idle', 'verified', 'partial', 'simplified'].includes(String(value.quality))
  current.value = { sessionId, value: valid ? (value as NpcBehaviorStatus) : null }
}

export function useNpcBehaviorStatus(sessionId: () => string | undefined) {
  return computed(() => (current.value.sessionId === sessionId() ? current.value.value : null))
}
