<script setup lang="ts">
import { computed, ref } from 'vue'
import { Check, Copy, Download, OctagonAlert } from 'lucide-vue-next'

export interface GenerationErrorDiagnostics {
  model_category?: string
  category_label?: string
  provider?: string
  model?: string | null
  max_tokens?: number
  finish_reason?: string | null
  prompt_tokens?: number | null
  completion_tokens?: number | null
  reasoning_tokens?: number | null
}

export interface GenerationErrorDetails {
  error_id?: string
  stage?: string
  exception_type?: string
  server_log?: string
  diagnostics?: GenerationErrorDiagnostics
}

const props = defineProps<{
  content: string
  details?: GenerationErrorDetails
  timestamp?: string
  adventureId?: string
  adventureTitle?: string
}>()

const copied = ref(false)

const diagnosticRows = computed(() => {
  const d = props.details?.diagnostics
  if (!d) return []
  const rows: [string, unknown][] = [
    ['Model', d.model],
    ['Category', d.category_label],
    ['Provider', d.provider],
    ['Max tokens', d.max_tokens],
    ['Output tokens', d.completion_tokens],
    ['Reasoning tokens', d.reasoning_tokens],
    ['Finish reason', d.finish_reason],
  ]
  return rows.filter(([, value]) => value !== null && value !== undefined && value !== '')
})

// Plain-text report for bug reports; matches the server log entry via the error id.
const reportText = computed(() => {
  const d = props.details
  const lines = [
    'TaleWeaver generation error',
    `Time: ${props.timestamp || new Date().toISOString()}`,
    props.adventureTitle ? `Adventure: ${props.adventureTitle}` : '',
    props.adventureId ? `Adventure ID: ${props.adventureId}` : '',
    d?.error_id ? `Error ID: ${d.error_id}` : '',
    d?.stage ? `Stage: ${d.stage}` : '',
    d?.exception_type ? `Exception: ${d.exception_type}` : '',
    d?.server_log ? `Server log: ${d.server_log}` : '',
    '',
    'Message:',
    props.content,
  ]
  if (diagnosticRows.value.length) {
    lines.push('', 'Diagnostics:', ...diagnosticRows.value.map(([label, value]) => `  ${label}: ${value}`))
  }
  return lines.filter((line, idx) => line !== '' || lines[idx - 1] !== '').join('\n')
})

async function copyReport() {
  try {
    await navigator.clipboard.writeText(reportText.value)
    copied.value = true
    window.setTimeout(() => (copied.value = false), 2000)
  } catch (err) {
    console.error('Failed to copy error report:', err)
  }
}

function downloadReport() {
  const blob = new Blob([reportText.value], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `taleweaver-generation-error-${props.details?.error_id || Date.now()}.txt`
  link.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="flex justify-center w-full max-w-[95%] sm:max-w-[90%] self-center my-1 animate-fade-in">
    <div class="rounded-2xl border border-rose-500/30 bg-rose-500/5 p-3.5 sm:p-4 flex flex-col gap-3 w-full">
      <div class="flex items-center justify-center gap-2 text-xs font-black uppercase tracking-widest text-rose-400">
        <OctagonAlert class="w-4 h-4 shrink-0" />
        <span>Generation Error</span>
      </div>

      <p class="text-xs text-rose-200/90 leading-relaxed whitespace-pre-wrap break-words select-text bg-black/40 p-3 rounded-xl border border-rose-500/10 font-mono">
        {{ props.content }}
      </p>

      <dl v-if="diagnosticRows.length" class="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] bg-black/30 rounded-xl px-3 py-2 border border-white/5">
        <template v-for="[label, value] in diagnosticRows" :key="label">
          <dt class="text-slate-500 font-bold">{{ label }}</dt>
          <dd class="text-slate-300 font-mono break-all">{{ value }}</dd>
        </template>
      </dl>

      <div class="flex flex-wrap items-center justify-between gap-2">
        <span v-if="props.details?.error_id" class="text-[10px] text-slate-500 font-mono select-all">
          Error ID: {{ props.details.error_id }}
          <template v-if="props.details.server_log"> · server log: {{ props.details.server_log }}</template>
        </span>
        <div class="flex items-center gap-2 ml-auto">
          <button
            type="button"
            class="px-3 py-1.5 rounded-lg border border-white/10 text-[10px] font-black uppercase tracking-widest text-slate-300 hover:text-white hover:border-white/30 transition-colors flex items-center gap-1.5"
            title="Copy error report to clipboard"
            @click="copyReport"
          >
            <component :is="copied ? Check : Copy" class="w-3.5 h-3.5" />
            <span>{{ copied ? 'Copied' : 'Copy' }}</span>
          </button>
          <button
            type="button"
            class="px-3 py-1.5 rounded-lg border border-white/10 text-[10px] font-black uppercase tracking-widest text-slate-300 hover:text-white hover:border-white/30 transition-colors flex items-center gap-1.5"
            title="Save error report as text file"
            @click="downloadReport"
          >
            <Download class="w-3.5 h-3.5" />
            <span>Save</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
