<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ImagePlus, Loader2, X } from 'lucide-vue-next'
import type { PortraitTarget, PortraitOptions } from '@/composables/useSessionPortrait'
import NpcJournalDetails from './NpcJournalDetails.vue'
import type { NpcCard } from '@/composables/useNpcJournal'
import { getOriginalImageUrl } from '@/utils/game_icons'

const props = defineProps<{
  sessionId?: string
  npc: PortraitTarget
  busy: boolean
  error: string
  updated: boolean
}>()
const emit = defineEmits<{ close: []; generate: [options: PortraitOptions] }>()
const dialog = ref<HTMLDialogElement | null>(null)
const brokenImage = ref('')
const purpose = ref('repair')
const usePreviousImage = ref(false)
const changeDescription = ref('')
watch(purpose, (value) => { usePreviousImage.value = value === 'variation' && !!imageUrl.value })
const learnedCard = ref<NpcCard | null>(null)
const imageUrl = computed(() => props.updated ? props.npc.image_url : learnedCard.value?.image_url || props.npc.image_url)
const characterName = computed(() => learnedCard.value?.name ?? props.npc.name)
const description = computed(() => learnedCard.value?.description ?? props.npc.description)
watch(() => [props.sessionId, props.npc.id], () => {
  learnedCard.value = null
  brokenImage.value = ''
  purpose.value = 'repair'
  usePreviousImage.value = false
  changeDescription.value = ''
})
const automaticPortrait = computed(() => ['pending', 'running'].includes(learnedCard.value?.portrait_status || ''))
const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
onMounted(() => dialog.value?.showModal())
onBeforeUnmount(() => {
  dialog.value?.close()
  previousFocus?.focus()
})
</script>

<template>
  <dialog
    ref="dialog"
    aria-labelledby="npc-portrait-heading"
    class="npc-card-scroll m-auto w-[calc(100%_-_2rem)] max-w-3xl max-h-[90dvh] overflow-y-auto rounded-2xl border border-white/15 bg-slate-900 p-5 text-slate-200 shadow-2xl backdrop:bg-black/75"
    @cancel.prevent="emit('close')"
  >
    <div class="flex items-start justify-between gap-3 mb-4">
      <div>
        <h2 id="npc-portrait-heading" class="font-bold text-lg">{{ characterName }} — Character</h2>
        <p class="mt-1 text-xs text-slate-400">
          Character information and portrait for this session.
        </p>
      </div>
      <button
        type="button"
        :aria-label="busy ? 'Stop and close' : 'Close character'"
        class="p-2 rounded-lg hover:bg-white/10 shrink-0"
        @click="emit('close')"
      >
        <X class="w-5 h-5" />
      </button>
    </div>
    <div class="grid gap-5 sm:grid-cols-[12rem_minmax(0,1fr)] mb-5">
      <div class="space-y-3">
        <img
          v-if="imageUrl && brokenImage !== imageUrl"
          :src="getOriginalImageUrl(imageUrl)"
          :alt="characterName"
          class="mx-auto h-64 w-full max-w-60 rounded-xl object-contain bg-black/20 sm:h-72"
          @error="brokenImage = imageUrl || ''"
        />
        <div v-else class="h-44 sm:h-72 flex items-center justify-center rounded-xl bg-black/20 text-slate-500">
          No portrait yet
        </div>
        <button v-if="!imageUrl || brokenImage === imageUrl" type="button" :disabled="busy || automaticPortrait"
          class="mx-auto flex items-center justify-center gap-2 rounded-xl bg-amber-400 px-3 py-2 text-sm font-bold text-slate-950 disabled:opacity-50"
          @click="emit('generate', { use_previous_image: false, change_description: '' })">
          <Loader2 v-if="busy || automaticPortrait" class="h-4 w-4 animate-spin" />
          <ImagePlus v-else class="h-4 w-4" />
          {{ busy || automaticPortrait ? 'Generating…' : 'Generate portrait' }}
        </button>
      </div>
      <section class="min-w-0" aria-label="Current character description">
        <h3 class="text-sm font-semibold text-slate-100">About {{ characterName }}</h3>
        <p v-if="description" class="mt-3 text-sm leading-relaxed text-slate-300 whitespace-pre-wrap break-words">{{ description }}</p>
        <p v-else class="mt-3 text-sm text-slate-400">You have not learned much about this character yet.</p>
        <div v-if="learnedCard?.overview?.length" class="mt-4 border-t border-white/10 pt-3">
          <h4 class="text-xs font-semibold uppercase tracking-wide text-slate-400">General overview</h4>
          <ul class="mt-2 space-y-2 text-sm leading-relaxed text-slate-300">
            <li v-for="entry in learnedCard.overview.slice(0, 3)" :key="entry.id" class="whitespace-pre-wrap break-words"><span v-if="entry.source === 'claimed'" class="mr-1 text-xs text-amber-200">Claim:</span>{{ entry.text }}</li>
          </ul>
        </div>
      </section>
    </div>
    <NpcJournalDetails v-if="sessionId && npc.id" :session-id="sessionId" :npc-id="npc.id" @loaded="learnedCard = $event" />
    <p v-if="error" role="alert" class="mt-3 text-sm text-rose-300">{{ error }}</p>
    <p v-if="updated" role="status" class="mt-3 text-sm text-emerald-300">
      Portrait saved to this session.
    </p>
    <p v-if="busy" role="status" class="mt-3 text-sm text-amber-200">
      Generating portrait… The previous image stays until generation succeeds.
    </p>
    <details class="mt-4 rounded-xl border border-white/10 p-3">
      <summary class="cursor-pointer text-sm font-semibold">Portrait options</summary>
      <label class="mt-3 block text-xs">
        Purpose
        <select v-model="purpose" :disabled="busy" class="mt-1 w-full rounded bg-slate-800 p-2">
          <option value="repair">Fix an unsuccessful image / new portrait</option>
          <option value="variation">Change expression, action or setting</option>
        </select>
      </label>
      <label class="mt-3 flex items-start gap-2 text-xs">
        <input v-model="usePreviousImage" type="checkbox" :disabled="busy || !imageUrl" />
        Use previous portrait as a reference
      </label>
      <p class="mt-1 text-xs text-slate-400">
        Requires ComfyUI with an image/reference workflow. Leave off to avoid carrying over image defects.
        Identity preservation depends on the workflow and model.
      </p>
      <label class="mt-3 block text-xs">
        Requested change (optional)
        <textarea v-model="changeDescription" :disabled="busy" maxlength="1000" rows="2"
          placeholder="For example: a cautious smile; keep the same face and clothing."
          class="mt-1 w-full rounded bg-slate-800 p-2" />
      </label>
      <div class="mt-4 flex justify-end">
        <button
          type="button"
          :disabled="busy || automaticPortrait"
          class="px-4 py-2 rounded-xl bg-amber-400 text-slate-950 font-bold text-sm flex items-center gap-2 disabled:opacity-50"
          @click="emit('generate', { use_previous_image: usePreviousImage, change_description: changeDescription })"
        >
          <Loader2 v-if="busy" class="w-4 h-4 animate-spin" />
          <ImagePlus v-else class="w-4 h-4" />
          {{ busy || automaticPortrait ? 'Generating…' : imageUrl ? 'Regenerate portrait' : 'Generate portrait' }}
        </button>
      </div>
    </details>
    <div class="mt-5 flex justify-end">
      <button type="button" class="px-4 py-2 rounded-xl border border-white/15 hover:bg-white/5 text-sm" @click="emit('close')">
        {{ busy ? 'Stop and close' : 'Close' }}
      </button>
    </div>
  </dialog>
</template>

<style scoped>
.npc-card-scroll {
  scrollbar-width: none;
  overscroll-behavior: contain;
}
.npc-card-scroll::-webkit-scrollbar {
  display: none;
}
</style>
