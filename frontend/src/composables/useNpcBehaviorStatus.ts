import { computed, shallowRef } from 'vue'

export interface NpcBehaviorStatus {
  module_version: string
  mode: 'off' | 'shadow' | 'live'
  quality: 'idle' | 'verified' | 'simplified'
  reason: string
  cooldown_remaining: number
  unreviewed_turns: number
  total_simplified_turns: number
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
    ['idle', 'verified', 'simplified'].includes(String(value.quality))
  current.value = { sessionId, value: valid ? (value as NpcBehaviorStatus) : null }
}

export function useNpcBehaviorStatus(sessionId: () => string | undefined) {
  return computed(() => (current.value.sessionId === sessionId() ? current.value.value : null))
}
