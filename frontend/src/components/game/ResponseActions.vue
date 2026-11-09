<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue'
import { RotateCcw, Undo2 } from 'lucide-vue-next'
import { apiFetch } from '@/services/http'
import { useGameSocket } from '@/composables/useGameSocket'
import RegenerateMessageButton from './RegenerateMessageButton.vue'
import { isStoryMessage } from '@/utils/storyMessages'

const props = defineProps<{ gameId?: string; disabled?: boolean; compact?: boolean }>()
const socket = useGameSocket()
const latest = computed(() => [...socket.messages.value].reverse().find(isStoryMessage))
const busy = computed(() => props.disabled || socket.inputLocked.value || ['connecting', 'loading'].includes(socket.status.value) || !!socket.sheet.value?.agent_active)
const available = ref(false)
const undoBusy = computed(() => props.disabled || ['connecting', 'loading'].includes(socket.status.value) || !!socket.sheet.value?.agent_active)
const canUndo = computed(() => !!socket.sheet.value?.debug_mode && available.value && !undoBusy.value)
const checking = ref(false)
const checkFailed = ref(false)
const reason = ref('Checking whether this turn can be regenerated…')
let version = 0
async function checkTurn() {
  const token = ++version
  available.value = false
  checking.value = false
  checkFailed.value = false
  reason.value = 'Complete a story turn before regenerating it.'
  if (!props.gameId || latest.value?.role !== 'assistant' || !latest.value.id) return
  if (!['connected', 'completed', 'game_over'].includes(socket.status.value)) return
  checking.value = true
  reason.value = 'Checking whether this turn can be regenerated…'
  try {
    const response = await apiFetch(`/adventures/${encodeURIComponent(props.gameId)}/chat/replay`)
    if (!response.ok) throw new Error('Could not check turn snapshot.')
    const data = await response.json()
    if (token !== version) return
    available.value = data.available && data.message_id === latest.value?.id
    reason.value = data.reason || 'Repeat your last action with new mechanics and narration.'
  } catch {
    if (token !== version) return
    checkFailed.value = true
    reason.value = 'Could not check the turn snapshot. Retry the check to enable regeneration.'
  } finally {
    if (token === version) checking.value = false
  }
}
watch(() => [props.gameId, latest.value?.id, socket.status.value], checkTurn, { immediate: true })
onScopeDispose(() => { version++ })

async function replay() {
  if (!available.value || busy.value || !latest.value?.id) return
  if (!window.confirm('Regenerate the entire last turn? This restores the world before your last message and replaces its consequences and reply. If generation fails, the previous result is restored.')) return
  const id = latest.value.id
  const user = [...socket.messages.value].reverse().find(m => m.role === 'user' && isStoryMessage(m))
  if (user) await socket.sendMessage(user.content, true, id)
}
async function undo() {
  if (!canUndo.value || !latest.value?.id) return
  if (!window.confirm('Undo the entire last turn? This removes your action, its reply and all consequences, and restores characters, clothing, items, locations and game time.')) return
  await socket.deleteMessage(latest.value.id)
}
</script>

<template>
  <div class="flex items-center gap-2" :class="compact ? 'shrink-0' : 'flex-wrap p-2'" aria-label="Response actions">
    <RegenerateMessageButton :game-id="gameId" :disabled="disabled" :compact="compact" show-label />
    <button type="button" :disabled="busy || !available" :title="reason"
      class="flex shrink-0 items-center gap-2 border text-xs text-slate-200 disabled:opacity-40 disabled:cursor-not-allowed"
      :class="compact ? 'rounded-xl border-slate-700/80 bg-slate-900/90 px-3 py-1.5 font-bold hover:border-amber-400' : 'rounded-lg border-slate-600 px-3 py-2'"
      @click="replay">
      <RotateCcw :size="15" /> <span :class="{ 'uppercase tracking-wider': compact }">{{ compact ? 'Regenerate' : 'Regenerate turn' }}</span>
    </button>
    <button v-if="socket.sheet.value?.debug_mode" type="button" :disabled="!canUndo" :title="available ? 'Undo the whole last turn and its consequences.' : 'Use a Chronicles checkpoint for older turns.'"
      class="flex shrink-0 items-center gap-2 rounded-lg border border-rose-500/40 px-3 py-1.5 text-xs text-rose-200 disabled:opacity-40 disabled:cursor-not-allowed"
      @click="undo">
      <Undo2 :size="15" /> Undo turn
    </button>
    <span v-if="!compact && !available && !busy" class="text-xs text-slate-400">{{ reason }}</span>
    <button v-if="checkFailed" type="button" :disabled="busy || checking"
      class="flex items-center gap-1 rounded-lg border border-amber-400/40 px-3 py-1.5 text-xs text-amber-200 disabled:opacity-40"
      @click="checkTurn">
      <RotateCcw :size="13" /> Retry turn check
    </button>
  </div>
</template>
