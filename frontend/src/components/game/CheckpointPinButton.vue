<script setup lang="ts">
import { ref, watch } from 'vue'
import type { SessionCheckpoint } from '@/types'
import { apiFetch } from '@/services/http'
import { useNotifications } from '@/composables/useNotifications'
const props = defineProps<{ checkpoint: SessionCheckpoint }>()
const pinned = ref(Boolean(props.checkpoint.pinned))
const busy = ref(false)
const { addNotification } = useNotifications()
watch(() => props.checkpoint, value => { pinned.value = Boolean(value.pinned) })
async function toggle() {
  if (busy.value) return
  busy.value = true
  const checkpoint = props.checkpoint
  try {
    const response = await apiFetch(`/adventures/sessions/${encodeURIComponent(checkpoint.session_id)}/checkpoints/${encodeURIComponent(checkpoint.id)}/pin`, {
      method: 'PATCH', includeJson: true, body: JSON.stringify({ pinned: !pinned.value }),
    })
    if (!response.ok) throw new Error('Could not update checkpoint protection. Refresh and try again.')
    const data = await response.json()
    if (props.checkpoint.id === checkpoint.id) pinned.value = data.pinned
  } catch (error) {
    addNotification(error instanceof Error ? error.message : 'Could not update checkpoint.', 'error')
  } finally { busy.value = false }
}
</script>
<template>
  <button type="button" :disabled="busy" :aria-pressed="pinned" class="mr-3 rounded-lg border border-slate-500 px-3 py-2 text-xs text-slate-200 disabled:opacity-40" @click="toggle">{{ pinned ? 'Unpin checkpoint' : 'Keep checkpoint' }}</button>
</template>
