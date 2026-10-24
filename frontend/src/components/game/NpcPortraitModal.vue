<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ImagePlus, Loader2, X } from 'lucide-vue-next'
import type { PortraitTarget } from '@/composables/useSessionPortrait'
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
const emit = defineEmits<{ close: []; generate: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)
const brokenImage = ref('')
const learnedCard = ref<NpcCard | null>(null)
const imageUrl = computed(() => props.updated ? props.npc.image_url : learnedCard.value?.image_url || props.npc.image_url)
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
    class="m-auto w-[calc(100%_-_2rem)] max-w-md max-h-[90dvh] overflow-y-auto rounded-2xl border border-white/15 bg-slate-900 p-5 text-slate-200 shadow-2xl backdrop:bg-black/75"
    @cancel.prevent="emit('close')"
  >
    <div class="flex items-start justify-between gap-3 mb-4">
      <div>
        <h2 id="npc-portrait-heading" class="font-bold text-lg">{{ npc.name }} — Character</h2>
        <p class="mt-1 text-xs text-slate-400">
          Character information and portrait for this session.
        </p>
      </div>
      <button
        type="button"
        :aria-label="busy ? 'Stop and close' : 'Close portrait'"
        class="p-2 rounded-lg hover:bg-white/10 shrink-0"
        @click="emit('close')"
      >
        <X class="w-5 h-5" />
      </button>
    </div>
    <img
      v-if="imageUrl && brokenImage !== imageUrl"
      :src="getOriginalImageUrl(imageUrl)"
      :alt="npc.name"
      class="mx-auto h-64 max-w-full rounded-xl object-contain bg-black/20"
      @error="brokenImage = imageUrl || ''"
    />
    <div v-else class="h-40 flex items-center justify-center rounded-xl bg-black/20 text-slate-500">
      No portrait yet
    </div>
    <p
      v-if="npc.description"
      class="mt-3 text-sm text-slate-300 max-h-28 overflow-y-auto whitespace-pre-wrap"
    >
      {{ npc.description }}
    </p>
    <p v-if="error" role="alert" class="mt-3 text-sm text-rose-300">{{ error }}</p>
    <p v-if="updated" role="status" class="mt-3 text-sm text-emerald-300">
      Portrait saved to this session.
    </p>
    <p v-if="busy" role="status" class="mt-3 text-sm text-amber-200">
      Generating portrait… The previous image stays until generation succeeds.
    </p>
    <div class="mt-5 flex flex-wrap justify-end gap-2">
      <button
        type="button"
        class="px-4 py-2 rounded-xl border border-white/15 hover:bg-white/5 text-sm"
        @click="emit('close')"
      >
        {{ busy ? 'Stop and close' : 'Close' }}
      </button>
      <button
        type="button"
        :disabled="busy || automaticPortrait"
        class="px-4 py-2 rounded-xl bg-amber-400 text-slate-950 font-bold text-sm flex items-center gap-2 disabled:opacity-50"
        @click="emit('generate')"
      >
        <Loader2 v-if="busy" class="w-4 h-4 animate-spin" />
        <ImagePlus v-else class="w-4 h-4" />
        {{ busy || automaticPortrait ? 'Generating…' : imageUrl ? 'Regenerate portrait' : 'Generate portrait' }}
      </button>
    </div>
    <NpcJournalDetails v-if="sessionId && npc.id" :session-id="sessionId" :npc-id="npc.id" @loaded="learnedCard = $event" />
  </dialog>
</template>
