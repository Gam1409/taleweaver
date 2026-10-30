<script setup lang="ts">
import { ref, watch } from 'vue'
import { useSessionContentSettings } from '@/composables/useSessionContentSettings'

const props = defineProps<{ sessionId: string }>()
const { draft, loaded, dirty, busy, error, load, save } = useSessionContentSettings(() => props.sessionId)
const gate = ref<HTMLDialogElement | null>(null)
const confirmation = ref('')
const gateError = ref('')
const levels = ['soft', 'medium', 'hard'] as const

function toggle(event: Event) {
  const target = event.target as HTMLInputElement
  if (!target.checked) {
    draft.value.enabled = false
    return
  }
  target.checked = draft.value.enabled
  confirmation.value = ''
  gateError.value = ''
  gate.value?.showModal()
}

function confirm() {
  if (confirmation.value.trim() !== 'NSFW') {
    gateError.value = 'Type exactly NSFW to confirm.'
    return
  }
  draft.value.enabled = true
  gate.value?.close()
}

watch(() => props.sessionId, () => gate.value?.close())
defineExpose({ save })
</script>

<template>
  <details class="rounded-2xl border border-pink-400/20 bg-pink-400/5 p-4">
    <summary class="cursor-pointer font-semibold text-pink-200">Mature content</summary>
    <p class="mt-3 text-xs text-slate-400">
      Applies to future VN narration and supported image generation in this session only.
      Your progress and the adventure template stay unchanged. Existing replies and images are kept.
    </p>
    <p class="mt-2 text-xs text-slate-400">Image generation also uses the selected image profile's Mature themes setting.</p>
    <p v-if="busy" role="status" class="mt-3 text-sm text-slate-400">Loading or saving content settings…</p>
    <p v-if="error" role="alert" class="mt-3 text-sm text-rose-300">
      {{ error }}
      <button type="button" :disabled="busy" class="ml-1 underline" @click="load">Reload settings</button>
    </p>
    <fieldset :disabled="!loaded || busy" class="mt-3 space-y-3 disabled:opacity-50">
      <label class="flex cursor-pointer items-center gap-3 text-sm font-semibold text-pink-300">
        <input type="checkbox" :checked="draft.enabled" class="h-4 w-4 accent-pink-400" @change="toggle" />
        Mature content
      </label>
      <div v-if="draft.enabled" role="group" aria-label="Content level" class="flex rounded-xl border border-white/10 bg-slate-950/50 p-1">
        <button v-for="level in levels" :key="level" type="button" :aria-pressed="draft.level === level"
          class="flex-1 rounded-lg px-3 py-2 text-xs font-bold uppercase focus-visible:outline focus-visible:outline-2 focus-visible:outline-pink-400"
          :class="draft.level === level ? 'bg-pink-600 text-white' : 'text-slate-400 hover:text-slate-200'"
          @click="draft.level = level">{{ level }}</button>
      </div>
    </fieldset>
    <p v-if="dirty" role="status" class="mt-3 text-xs text-amber-300">Unsaved changes — use Save settings below.</p>
  </details>
  <Teleport to="body">
    <dialog ref="gate" aria-label="Enable mature content" class="m-auto w-80 rounded-2xl border border-pink-400/30 bg-slate-950 p-6 text-slate-200 backdrop:bg-black/70">
      <form @submit.prevent="confirm">
        <h3 class="font-bold text-pink-300">Enable mature content</h3>
        <label class="mt-3 block text-sm">Type NSFW to confirm.
          <input v-model="confirmation" autofocus type="text" autocomplete="off" class="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 p-2" />
        </label>
        <p v-if="gateError" role="alert" class="mt-2 text-sm text-rose-300">{{ gateError }}</p>
        <div class="mt-4 flex justify-end gap-3">
          <button type="button" class="px-3 py-2" @click="gate?.close()">Cancel</button>
          <button type="submit" class="rounded-lg bg-pink-600 px-3 py-2 font-semibold text-white">Confirm</button>
        </div>
      </form>
    </dialog>
  </Teleport>
</template>
