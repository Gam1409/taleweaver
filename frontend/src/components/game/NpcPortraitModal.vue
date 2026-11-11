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
watch(purpose, value => {
  usePreviousImage.value = value === 'variation' && !!imageUrl.value
})
const learnedCard = ref<NpcCard | null>(null)
const imageUrl = computed(() =>
  props.updated ? props.npc.image_url : learnedCard.value?.image_url || props.npc.image_url
)
const characterName = computed(() => learnedCard.value?.name ?? props.npc.name)
const description = computed(() => learnedCard.value?.description ?? props.npc.description)
watch(
  () => [props.sessionId, props.npc.id],
  () => {
    learnedCard.value = null
    brokenImage.value = ''
    purpose.value = 'repair'
    usePreviousImage.value = false
    changeDescription.value = ''
  }
)
const automaticPortrait = computed(() =>
  ['pending', 'running'].includes(learnedCard.value?.portrait_status || '')
)
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
    class="m-auto h-[min(54rem,92dvh)] max-h-[92dvh] w-[calc(100%_-_1rem)] max-w-6xl overflow-hidden rounded-2xl border border-white/15 bg-slate-900 p-0 text-slate-200 shadow-2xl backdrop:bg-black/75 sm:w-[calc(100%_-_2rem)]"
    @cancel.prevent="emit('close')"
  >
    <div class="flex h-full min-h-0 flex-col">
      <header
        class="flex shrink-0 items-start justify-between gap-3 border-b border-white/10 px-5 py-4"
      >
        <div class="min-w-0">
          <h2 id="npc-portrait-heading" class="break-words text-lg font-bold">
            {{ characterName }} — Character
          </h2>
          <p class="mt-1 text-xs text-slate-400">
            Current observations and the history you have learned.
          </p>
        </div>
        <button
          type="button"
          :aria-label="busy ? 'Stop and close' : 'Close character'"
          class="shrink-0 rounded-lg p-2 hover:bg-white/10"
          @click="emit('close')"
        >
          <X class="h-5 w-5" />
        </button>
      </header>
      <div
        class="flex min-h-0 flex-1 flex-col sm:grid sm:grid-cols-[15rem_minmax(0,1fr)] lg:grid-cols-[18rem_minmax(0,1fr)]"
      >
        <aside
          aria-label="Character profile"
          class="npc-card-scroll grid max-h-[38dvh] shrink-0 grid-cols-[5.5rem_minmax(0,1fr)] gap-3 overflow-y-auto border-b border-white/10 bg-slate-950/35 p-4 sm:block sm:max-h-none sm:border-b-0 sm:border-r sm:p-5"
        >
          <div class="space-y-3">
            <img
              v-if="imageUrl && brokenImage !== imageUrl"
              :src="getOriginalImageUrl(imageUrl)"
              :alt="characterName"
              class="mx-auto h-28 w-full rounded-xl bg-black/20 object-contain sm:h-64"
              @error="brokenImage = imageUrl || ''"
            />
            <div
              v-else
              class="flex h-28 items-center justify-center rounded-xl bg-black/20 text-center text-xs text-slate-500 sm:h-64"
            >
              No portrait yet
            </div>
            <button
              v-if="!imageUrl || brokenImage === imageUrl"
              type="button"
              :disabled="busy || automaticPortrait"
              class="mx-auto flex items-center justify-center gap-2 rounded-xl bg-amber-400 px-3 py-2 text-xs font-bold text-slate-950 disabled:opacity-50"
              @click="emit('generate', { use_previous_image: false, change_description: '' })"
            >
              <Loader2
                v-if="busy || automaticPortrait"
                class="h-4 w-4 shrink-0 animate-spin"
              /><ImagePlus v-else class="h-4 w-4 shrink-0" />
              {{ busy || automaticPortrait ? 'Generating…' : 'Generate portrait' }}
            </button>
          </div>
          <section class="min-w-0 sm:mt-5" aria-label="Character description">
            <h3 class="text-sm font-semibold text-slate-100">About {{ characterName }}</h3>
            <p
              v-if="learnedCard?.gender || learnedCard?.age_years != null"
              class="mt-2 text-xs text-slate-400"
            >
              <span v-if="learnedCard.gender"
                >{{ learnedCard.gender }}<span v-if="learnedCard.age_years != null"> · </span></span
              >
              <span v-if="learnedCard.age_years != null">{{ learnedCard.age_years }} years</span>
            </p>
            <span
              v-if="learnedCard?.narrative_role === 'major'"
              class="mt-2 inline-block rounded-full border border-rose-400/30 bg-rose-400/10 px-2 py-1 text-xs text-rose-200"
              >Major character</span
            >
            <p
              v-if="description"
              class="npc-card-scroll mt-2 max-h-24 overflow-y-auto whitespace-pre-wrap break-words pr-1 text-sm leading-relaxed text-slate-300 sm:max-h-48"
            >
              {{ description }}
            </p>
            <p v-else class="mt-2 text-sm text-slate-400">
              You have not learned much about this character yet.
            </p>
            <div
              v-if="learnedCard?.overview?.length"
              class="mt-4 hidden border-t border-white/10 pt-3 sm:block"
            >
              <h4 class="text-xs font-semibold uppercase tracking-wide text-slate-400">
                General overview
              </h4>
              <ul class="mt-2 space-y-2 text-sm leading-relaxed text-slate-300">
                <li
                  v-for="entry in learnedCard.overview.slice(0, 3)"
                  :key="entry.id"
                  class="whitespace-pre-wrap break-words"
                >
                  <span v-if="entry.source === 'claimed'" class="mr-1 text-xs text-amber-200"
                    >Claim:</span
                  >{{ entry.text }}
                </li>
              </ul>
            </div>
          </section>
          <p v-if="error" role="alert" class="col-span-2 mt-3 text-sm text-rose-300">{{ error }}</p>
          <p v-if="updated" role="status" class="col-span-2 mt-3 text-sm text-emerald-300">
            Portrait saved to this session.
          </p>
          <p v-if="busy" role="status" class="col-span-2 mt-3 text-sm text-amber-200">
            Generating portrait… The previous image stays until generation succeeds.
          </p>
          <details class="col-span-2 mt-3 rounded-xl border border-white/10 p-3">
            <summary class="cursor-pointer text-sm font-semibold">Portrait options</summary>
            <label class="mt-3 block text-xs">
              Purpose
              <select
                v-model="purpose"
                :disabled="busy"
                class="mt-1 w-full rounded bg-slate-800 p-2"
              >
                <option value="repair">Fix an unsuccessful image / new portrait</option>
                <option value="variation">Change expression, action or setting</option>
              </select>
            </label>
            <label class="mt-3 flex items-start gap-2 text-xs">
              <input v-model="usePreviousImage" type="checkbox" :disabled="busy || !imageUrl" />
              Use previous portrait as a reference
            </label>
            <p class="mt-1 text-xs text-slate-400">
              Requires ComfyUI with an image/reference workflow. Leave off to avoid carrying over
              image defects. Identity preservation depends on the workflow and model.
            </p>
            <label class="mt-3 block text-xs">
              Requested change (optional)
              <textarea
                v-model="changeDescription"
                :disabled="busy"
                maxlength="1000"
                rows="2"
                placeholder="For example: a cautious smile; keep the same face and clothing."
                class="mt-1 w-full rounded bg-slate-800 p-2"
              />
            </label>
            <div class="mt-4 flex justify-end">
              <button
                type="button"
                :disabled="busy || automaticPortrait"
                class="px-4 py-2 rounded-xl bg-amber-400 text-slate-950 font-bold text-sm flex items-center gap-2 disabled:opacity-50"
                @click="
                  emit('generate', {
                    use_previous_image: usePreviousImage,
                    change_description: changeDescription
                  })
                "
              >
                <Loader2 v-if="busy" class="w-4 h-4 animate-spin" />
                <ImagePlus v-else class="w-4 h-4" />
                {{
                  busy || automaticPortrait
                    ? 'Generating…'
                    : imageUrl
                      ? 'Regenerate portrait'
                      : 'Generate portrait'
                }}
              </button>
            </div>
          </details>
        </aside>
        <NpcJournalDetails
          v-if="sessionId && npc.id"
          :session-id="sessionId"
          :npc-id="npc.id"
          @loaded="learnedCard = $event"
        />
        <section v-else class="min-h-0 overflow-y-auto p-5 text-sm text-slate-400">
          State and history become available in a saved session.
        </section>
      </div>
      <footer class="flex shrink-0 justify-end border-t border-white/10 px-5 py-3">
        <button
          type="button"
          class="rounded-xl border border-white/15 px-4 py-2 text-sm hover:bg-white/5"
          @click="emit('close')"
        >
          {{ busy ? 'Stop and close' : 'Close' }}
        </button>
      </footer>
    </div>
  </dialog>
</template>

<style scoped>
.npc-card-scroll {
  scrollbar-width: thin;
  scrollbar-color: #64748b transparent;
  overscroll-behavior: contain;
}
.npc-card-scroll::-webkit-scrollbar {
  width: 8px;
}
.npc-card-scroll::-webkit-scrollbar-thumb {
  background: #64748b;
  border-radius: 999px;
}
</style>
