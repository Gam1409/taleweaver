<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Pencil, X } from 'lucide-vue-next'
import {
  CORRECTION_MAX_LENGTH, clearCorrection, correctionPresets, getCorrection, queueCorrection,
} from '@/services/narrationCorrection'

const props = defineProps<{ gameId?: string; disabled?: boolean }>()
const dialog = ref<HTMLDialogElement | null>(null)
const input = ref<HTMLTextAreaElement | null>(null)
const custom = ref(false)
const draft = ref('')
const pending = computed(() => getCorrection(props.gameId))
const valid = computed(() => Boolean(draft.value.trim()) && draft.value.length <= CORRECTION_MAX_LENGTH)

function open() {
  custom.value = false
  dialog.value?.showModal()
}

function choose(label: string, text: string) {
  if (!props.gameId || props.disabled) return
  queueCorrection(props.gameId, label, text)
  dialog.value?.close()
}

async function openCustom() {
  draft.value = pending.value?.text || ''
  custom.value = true
  await nextTick()
  input.value?.focus()
}

function clear() {
  if (props.gameId) clearCorrection(props.gameId)
  dialog.value?.close()
}

watch(() => [props.gameId, props.disabled], () => dialog.value?.close())
</script>

<template>
  <button type="button" :disabled="disabled || !gameId" aria-label="Correct the narrator"
    :title="pending ? `Correction queued: ${pending.label}` : 'Correct the narrator'"
    aria-haspopup="dialog" class="relative shrink-0 rounded-lg border border-slate-700/70 bg-transparent p-2 text-slate-300 hover:border-amber-400 hover:text-amber-300 disabled:opacity-40 disabled:cursor-not-allowed"
    @click="open">
    <Pencil :size="16" aria-hidden="true" />
    <span v-if="pending" class="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-amber-400 ring-2 ring-slate-950" aria-hidden="true" />
    <span class="sr-only" role="status">{{ pending ? 'Correction queued for the next response' : '' }}</span>
  </button>
  <Teleport to="body">
    <dialog ref="dialog" aria-label="Narrator correction" class="m-auto w-[min(28rem,calc(100vw-2rem))] max-h-[85vh] overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 p-5 text-slate-100 shadow-xl backdrop:bg-black/70">
      <div class="mb-3 flex items-center justify-between gap-3">
        <h2 class="text-lg font-bold">{{ custom ? 'Your correction' : 'Correct the narrator' }}</h2>
        <button type="button" aria-label="Close" class="rounded p-1 hover:bg-slate-800" @click="dialog?.close()"><X :size="20" /></button>
      </div>
      <p class="mb-4 text-sm text-slate-400">Applies once to the next response, Rewrite, or Regenerate. Nothing starts now. This note stays outside the story.</p>
      <form v-if="custom" class="space-y-3" @submit.prevent="choose('Custom correction', draft)">
        <label for="narrator-correction-text" class="block text-sm">What should the narrator correct?</label>
        <textarea id="narrator-correction-text" ref="input" v-model="draft" :maxlength="CORRECTION_MAX_LENGTH" rows="5"
          class="w-full resize-y rounded-lg border border-slate-600 bg-slate-950 p-3 text-sm focus:border-amber-400 focus:outline-none" />
        <div class="text-right text-xs text-slate-400">{{ draft.length }} / {{ CORRECTION_MAX_LENGTH }}</div>
        <div class="flex justify-end gap-3">
          <button type="button" class="px-3 py-2 text-sm text-slate-300" @click="custom = false">Back</button>
          <button type="submit" :disabled="!valid || disabled" class="rounded-lg bg-amber-400 px-3 py-2 text-sm font-bold text-slate-950 disabled:opacity-40">Queue correction</button>
        </div>
      </form>
      <div v-else class="space-y-2">
        <button v-for="preset in correctionPresets" :key="preset.label" type="button" :title="preset.text" :disabled="disabled"
          class="block w-full rounded-lg border border-slate-700 px-3 py-2 text-left text-sm hover:border-amber-400 hover:bg-slate-800"
          @click="choose(preset.label, preset.text)">{{ preset.label }}</button>
        <button type="button" aria-label="Write a custom correction" class="block w-full rounded-lg border border-slate-700 px-3 py-2 text-left hover:border-amber-400 hover:bg-slate-800" @click="openCustom">…</button>
      </div>
      <div v-if="pending" class="mt-4 border-t border-slate-700 pt-3 text-sm">
        <p class="text-amber-300">Queued: {{ pending.label }}</p>
        <p class="mt-2 whitespace-pre-wrap break-words text-xs text-slate-400">{{ pending.text }}</p>
        <button type="button" class="mt-2 text-slate-300 underline" @click="clear">Remove correction</button>
      </div>
    </dialog>
  </Teleport>
</template>
