<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RotateCcw } from 'lucide-vue-next'
import { apiFetch } from '@/services/http'
import { useGameSocket } from '@/composables/useGameSocket'
import RegenerateMessageButton from './RegenerateMessageButton.vue'

const props = defineProps<{ gameId?: string; disabled?: boolean }>()
const socket = useGameSocket()
const latest = computed(() => [...socket.messages.value].reverse().find(m => m.role === 'user' || m.role === 'assistant'))
const busy = computed(() => ['connecting', 'loading'].includes(socket.status.value) || !!socket.sheet.value?.agent_active)
const available = ref(false)
const reason = ref('Checking whether this turn can be regenerated…')
let version = 0
watch(() => [props.gameId, latest.value?.id, socket.status.value], async () => {
  const token = ++version
  available.value = false
  if (!props.gameId || latest.value?.role !== 'assistant' || !latest.value.id) return
  if (!['connected', 'completed', 'game_over'].includes(socket.status.value)) return
  try {
    const response = await apiFetch(`/adventures/${encodeURIComponent(props.gameId)}/chat/replay`)
    if (!response.ok) throw new Error('Could not check turn snapshot.')
    const data = await response.json()
    if (token !== version) return
    available.value = data.available && data.message_id === latest.value?.id
    reason.value = data.reason || 'Repeat your last action with new mechanics and narration.'
  } catch {
    if (token === version) reason.value = 'Could not check the turn snapshot. Reopen the session to retry.'
  }
}, { immediate: true })

async function replay() {
  if (!available.value || busy.value || !latest.value?.id) return
  if (!window.confirm('Regenerate the entire last turn? This restores the world before your last message and replaces its consequences and reply. If generation fails, the previous result is restored.')) return
  const id = latest.value.id
  const user = [...socket.messages.value].reverse().find(m => m.role === 'user')
  if (user) await socket.sendMessage(user.content, true, id)
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-2 p-2" aria-label="Response actions">
    <RegenerateMessageButton :game-id="gameId" :disabled="disabled" show-label />
    <button type="button" :disabled="busy || !available" :title="reason"
      class="flex items-center gap-2 rounded-lg border border-slate-600 px-3 py-2 text-xs text-slate-200 disabled:opacity-40"
      @click="replay">
      <RotateCcw :size="15" /> Regenerate turn
    </button>
    <span v-if="!available && !busy" class="text-xs text-slate-400">{{ reason }}</span>
  </div>
</template>
