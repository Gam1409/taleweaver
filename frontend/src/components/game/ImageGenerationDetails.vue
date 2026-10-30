<script setup lang="ts">
import { computed, ref } from 'vue'
import { Info, X } from 'lucide-vue-next'

const props = defineProps<{ details?: Record<string, unknown> | null }>()
const dialog = ref<HTMLDialogElement | null>(null)
const fields = computed(() => [
  ['provider', 'Provider'], ['model', 'Model'], ['workflow', 'Workflow'],
  ['seed', 'Seed'], ['width', 'Width'], ['height', 'Height'],
  ['trace_id', 'Local trace ID'],
].filter(([key]) => props.details?.[key] !== undefined))
</script>

<template>
  <button type="button" title="Generation details" aria-label="Generation details"
    class="inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-1 text-[11px] text-slate-400/70 transition-colors hover:bg-white/5 hover:text-slate-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400"
    @click="dialog?.showModal()">
    <Info :size="13" aria-hidden="true" /> Generation details
  </button>
  <Teleport to="body">
    <dialog ref="dialog" aria-label="Generation details"
      class="m-auto max-h-[85dvh] w-[min(42rem,calc(100vw-2rem))] overflow-y-auto rounded-xl border border-slate-700 bg-slate-900 p-5 text-slate-200 shadow-xl backdrop:bg-black/60">
      <header class="mb-4 flex items-center justify-between gap-3">
        <h2 class="text-base font-semibold">Generation details</h2>
        <button type="button" aria-label="Close generation details" autofocus class="rounded p-2 hover:bg-white/10" @click="dialog?.close()"><X :size="18" /></button>
      </header>
      <template v-if="details">
        <p class="mb-4 text-xs text-slate-400">Saved for this image when it was generated. Current settings may differ.</p>
        <dl class="mb-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <template v-for="[key, label] in fields" :key="key">
            <dt class="text-slate-400">{{ label }}</dt><dd class="break-words">{{ details[key] }}</dd>
          </template>
        </dl>
        <h3 class="mb-2 text-sm font-semibold">Positive prompt</h3>
        <pre class="mb-4 select-text whitespace-pre-wrap break-words rounded-lg bg-slate-950 p-3 font-sans text-sm">{{ details.positive_prompt ?? 'Not recorded.' }}</pre>
        <h3 class="mb-2 text-sm font-semibold">Negative prompt</h3>
        <pre class="select-text whitespace-pre-wrap break-words rounded-lg bg-slate-950 p-3 font-sans text-sm">{{ details.negative_prompt === '' ? 'Empty.' : (details.negative_prompt ?? 'Not recorded or no mapped negative-prompt input.') }}</pre>
      </template>
      <p v-else class="text-sm text-slate-400">Generation details were not saved for this image. They will be recorded when you generate a new illustration.</p>
    </dialog>
  </Teleport>
</template>
