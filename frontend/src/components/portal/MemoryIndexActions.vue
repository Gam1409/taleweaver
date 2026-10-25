<script setup lang="ts">
import { ref } from 'vue'
import { Database } from 'lucide-vue-next'
import { memoryRagService } from '@/services/memoryRagService'
import type { MemoryIndexStatus } from '@/services/memoryRagService'

const props = defineProps<{ templateId: string; title: string }>()
const dialog = ref<HTMLDialogElement | null>(null)
const status = ref<MemoryIndexStatus | null>(null)
const busy = ref(false)
const error = ref('')
const message = ref('')
const confirm = ref<'clear' | 'rebuild' | null>(null)

async function load(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    status.value = await memoryRagService.getIndex(props.templateId)
  } catch {
    error.value = 'Could not load this adventure’s memory index. Try again.'
  } finally {
    busy.value = false
  }
}

async function open(): Promise<void> {
  confirm.value = null
  message.value = ''
  status.value = null
  dialog.value?.showModal()
  await load()
}

async function perform(): Promise<void> {
  const action = confirm.value
  if (!action) return
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    if (action === 'clear') {
      await memoryRagService.clearIndex(props.templateId)
      message.value = 'Memory index cleared. Automatic indexing is paused until you rebuild it.'
    } else {
      await memoryRagService.rebuildIndex(props.templateId)
      message.value = 'Rebuild queued. Memories will be indexed in the background.'
    }
    confirm.value = null
    await load()
  } catch {
    error.value =
      action === 'clear'
        ? 'The memory index could not be cleared. Try again.'
        : 'The rebuild could not start. Enable memory recall and check its settings, then try again.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <button
    type="button"
    class="w-full text-left px-3 py-2 text-xs text-slate-300 hover:bg-white/10 hover:text-white flex items-center gap-2 rounded-lg"
    @click.stop="open"
  >
    <Database class="w-3.5 h-3.5 shrink-0" />
    Memory index
  </button>
  <Teleport to="body">
    <dialog
      ref="dialog"
      class="memory-dialog w-[calc(100%-2rem)] max-w-lg rounded-2xl border border-white/15 bg-slate-900 p-0 text-left text-slate-200 shadow-2xl"
      :aria-labelledby="`memory-index-title-${props.templateId}`"
      @click.stop
      @mousedown.stop
      @cancel="busy && $event.preventDefault()"
    >
      <div class="p-6 space-y-4">
        <h2 :id="`memory-index-title-${props.templateId}`" class="text-lg font-bold text-white">
          Memory index
        </h2>
        <p class="font-medium text-slate-300 break-words">{{ props.title }}</p>
        <p class="text-sm text-slate-400">
          Manage searchable memories for this adventure and your play sessions. Your adventure, game
          progress and history are kept.
        </p>
        <p v-if="busy" role="status" class="text-sm text-cyan-300">
          {{ confirm ? 'Updating memory index…' : 'Loading memory index…' }}
        </p>
        <div
          v-if="status"
          class="rounded-xl border border-white/10 bg-white/5 p-4 text-sm space-y-2"
        >
          <p>
            {{
              status.paused
                ? 'Automatic indexing is paused.'
                : status.enabled
                  ? 'Memory recall is enabled.'
                  : 'Memory recall is disabled in settings.'
            }}
          </p>
          <p class="text-slate-400">
            {{ status.session_count }} sessions · {{ status.pending_count }} pending<span
              v-if="status.indexed_count !== undefined"
            >
              · {{ status.indexed_count }} indexed</span
            >
          </p>
        </div>
        <p v-if="confirm === 'clear'" class="text-sm text-amber-200">
          Clear the memory index for this adventure and all your sessions? Automatic indexing will
          pause. Choose Rebuild memory index when you want to restore recall.
        </p>
        <p v-if="confirm === 'rebuild'" class="text-sm text-amber-200">
          Rebuild searchable memories from this adventure’s saved session history? This uses your
          configured embeddings provider and resumes automatic indexing.
        </p>
        <p v-if="message" role="status" class="text-sm text-emerald-300">{{ message }}</p>
        <p v-if="error" role="alert" class="text-sm text-red-300">{{ error }}</p>
        <button
          v-if="error && !status"
          type="button"
          :disabled="busy"
          class="text-sm text-cyan-300 underline"
          @click="load"
        >
          Retry
        </button>
      </div>
      <div class="flex flex-wrap justify-end gap-3 border-t border-white/10 p-4">
        <button
          type="button"
          :disabled="busy"
          class="memory-button border-white/20 text-slate-200"
          @click="confirm ? (confirm = null) : dialog?.close()"
        >
          {{ confirm ? 'Cancel' : 'Close' }}
        </button>
        <template v-if="status && !confirm">
          <button
            type="button"
            :disabled="busy"
            class="memory-button border-red-400/30 text-red-300"
            @click="confirm = 'clear'"
          >
            Clear memory index
          </button>
          <button
            type="button"
            :disabled="busy || !status.enabled"
            class="memory-button border-cyan-400/40 text-cyan-300"
            @click="confirm = 'rebuild'"
          >
            Rebuild memory index
          </button>
        </template>
        <button
          v-if="confirm"
          type="button"
          :disabled="busy"
          class="memory-button border-cyan-400/40 bg-cyan-800 text-white"
          @click="perform"
        >
          {{ confirm === 'clear' ? 'Confirm clear' : 'Confirm rebuild' }}
        </button>
      </div>
    </dialog>
  </Teleport>
</template>

<style scoped>
.memory-dialog::backdrop {
  background: rgb(0 0 0 / 70%);
  backdrop-filter: blur(4px);
}
.memory-button {
  @apply rounded-lg border px-3 py-2 text-sm font-medium hover:bg-white/10 disabled:opacity-40 disabled:cursor-not-allowed;
}
</style>
