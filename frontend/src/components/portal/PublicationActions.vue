<script setup lang="ts">
import { ref } from 'vue'
import { Download } from 'lucide-vue-next'
import { adventurePublicationService } from '@/services/adventurePublication'
import type { PublicationReport } from '@/services/adventurePublication'

const props = defineProps<{ templateId: string; title: string }>()
const dialog = ref<HTMLDialogElement | null>(null)
const report = ref<PublicationReport | null>(null)
const busy = ref(false)
const acknowledged = ref(false)
const error = ref('')
const completed = ref(false)
async function preview() {
  busy.value = true
  report.value = null
  acknowledged.value = false
  error.value = ''
  completed.value = false
  try {
    report.value = await adventurePublicationService.preview(props.templateId)
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Compatibility check failed.'
  } finally {
    busy.value = false
  }
}
async function open() {
  dialog.value?.showModal()
  await preview()
}
async function download() {
  if (!report.value?.compatible || (report.value.requires_acknowledgement && !acknowledged.value))
    return
  busy.value = true
  error.value = ''
  try {
    const blob = await adventurePublicationService.export(props.templateId, acknowledged.value)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'adventure-original.adz'
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    completed.value = true
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Export failed.'
    report.value = null
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
    <Download class="w-3.5 h-3.5 shrink-0" /> Export for original TaleWeaver
  </button>
  <Teleport to="body">
    <dialog
      ref="dialog"
      class="publication-dialog w-[calc(100%-2rem)] max-w-lg rounded-2xl border border-white/15 bg-slate-900 p-0 text-left text-slate-200 shadow-2xl"
      :aria-labelledby="`publication-title-${templateId}`"
      @click.stop
      @mousedown.stop
      @cancel="busy && $event.preventDefault()"
    >
      <div class="p-6 space-y-4 max-h-[70vh] overflow-y-auto">
        <h2 :id="`publication-title-${templateId}`" class="text-lg font-bold text-white">
          Export for original TaleWeaver
        </h2>
        <p class="font-medium break-words">{{ title }}</p>
        <p class="text-sm text-slate-400">
          Prepare a compatible copy for sharing with the original project. Your adventure stays
          unchanged. Nothing is published online.
        </p>
        <p v-if="busy" role="status">
          {{ report ? 'Preparing download…' : 'Checking compatibility…' }}
        </p>
        <template v-if="report">
          <p class="text-sm">Story mode: {{ report.source_mode }} → {{ report.target_mode }}</p>
          <p v-if="!report.compatible" class="text-amber-200">
            This adventure cannot currently be exported safely to the original format.
          </p>
          <ul v-if="report.warnings.length" class="list-disc pl-5 space-y-2 text-sm text-amber-200">
            <li v-for="(warning, index) in report.warnings" :key="index">{{ warning }}</li>
          </ul>
          <p v-else class="text-sm text-emerald-300">
            No compatibility changes need your attention.
          </p>
          <label
            v-if="report.compatible && report.requires_acknowledgement"
            class="flex gap-3 text-sm"
          >
            <input
              v-model="acknowledged"
              type="checkbox"
              class="mt-1 accent-cyan-400"
              :disabled="busy"
            />
            <span>I understand the listed changes and want to export this compatible copy.</span>
          </label>
        </template>
        <p v-if="error" role="alert" class="text-sm text-red-300">{{ error }}</p>
        <p v-if="completed" role="status" class="text-sm text-emerald-300">
          Compatible copy downloaded. Review it before publishing.
        </p>
      </div>
      <div class="flex flex-wrap justify-end gap-3 border-t border-white/10 p-4">
        <button
          type="button"
          class="rounded-lg border border-white/20 px-3 py-2 text-sm disabled:opacity-50"
          :disabled="busy"
          @click="dialog?.close()"
        >
          Close
        </button>
        <button
          v-if="!report && !busy"
          type="button"
          class="rounded-lg border border-cyan-400/40 px-3 py-2 text-sm"
          @click="preview"
        >
          Check again
        </button>
        <button
          v-if="report?.compatible"
          type="button"
          class="rounded-lg border border-cyan-400/40 bg-cyan-800 px-3 py-2 text-sm disabled:opacity-50"
          :disabled="busy || (report.requires_acknowledgement && !acknowledged)"
          @click="download"
        >
          Download compatible copy
        </button>
      </div>
    </dialog>
  </Teleport>
</template>
<style scoped>
.publication-dialog::backdrop {
  background: rgb(2 6 23 / 78%);
  backdrop-filter: blur(5px);
}
</style>
