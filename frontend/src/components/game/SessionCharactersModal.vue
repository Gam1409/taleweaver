<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, toRef } from 'vue'
import { X, Users } from 'lucide-vue-next'
import { useNpcJournal, type NpcCard } from '@/composables/useNpcJournal'
import { useNpcCardSettings } from '@/composables/useNpcCardSettings'
import NpcCardPreferences from './NpcCardPreferences.vue'
import { getImageUrl } from '@/utils/game_icons'

const props = defineProps<{ sessionId: string }>()
const emit = defineEmits<{ close: []; select: [npc: NpcCard] }>()
const settings = useNpcCardSettings(toRef(props, 'sessionId'))
const { characters, loading, error, pending, failed, load, retryLearning } = useNpcJournal(toRef(props, 'sessionId'), ref(undefined), settings.showState)
const dialog = ref<HTMLDialogElement | null>(null)
const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
onMounted(() => dialog.value?.showModal())
const timer = setInterval(() => { if (!loading.value) void load() }, 5000)
onBeforeUnmount(() => { clearInterval(timer); dialog.value?.close(); previousFocus?.focus() })
</script>

<template>
  <dialog ref="dialog" aria-labelledby="characters-heading" class="character-directory-scroll m-auto w-[calc(100%_-_2rem)] max-w-lg max-h-[85dvh] overflow-y-auto rounded-2xl border border-white/15 bg-slate-900 p-5 text-slate-200 backdrop:bg-black/75" @cancel.prevent="emit('close')">
    <div class="flex justify-between items-center gap-4 mb-4">
      <h2 id="characters-heading" class="font-bold text-lg flex items-center gap-2"><Users class="w-5 h-5" /> Characters</h2>
      <button aria-label="Close characters" class="p-2 rounded-lg hover:bg-white/10" @click="emit('close')"><X class="w-5 h-5" /></button>
    </div>
    <p class="text-sm text-slate-400 mb-4">People you have met. New characters get a card when they introduce themselves by name.</p>
    <p v-if="pending" role="status" class="mb-3 text-sm text-amber-200">Learning about characters from {{ pending }} recent response(s)… You can keep playing.</p>
    <p v-if="failed" class="mb-3 text-sm text-rose-300">Some character information could not be saved. <button :disabled="loading" class="underline" @click="retryLearning">Retry learning</button></p>
    <p v-if="error" role="alert" class="mb-3 text-sm text-rose-300">{{ error }} <button class="underline" @click="load()">Retry</button></p>
    <p v-if="!characters.length && !loading && !error" class="text-slate-400">No known characters yet.</p>
    <p v-if="loading && !characters.length" role="status">Loading characters…</p>
    <ul class="space-y-2">
      <li v-for="npc in characters" :key="npc.id">
        <button class="w-full flex gap-3 items-center rounded-xl border border-slate-700 p-3 text-left hover:bg-slate-800 focus-visible:outline-amber-300" @click="emit('select', npc)">
          <img v-if="npc.image_url" :src="getImageUrl(npc.image_url)" alt="" class="w-12 h-16 rounded-lg object-cover" />
          <Users v-else class="w-12 h-12 p-3 text-slate-500" />
          <span class="min-w-0"><span class="block font-semibold">{{ npc.name }}</span><span v-if="npc.narrative_role === 'major'" class="block text-xs text-rose-200">Major character</span><span class="block text-xs text-slate-400">{{ npc.entry_count }} learned detail(s)</span></span>
        </button>
      </li>
    </ul>
    <NpcCardPreferences class="mt-4" :settings="settings" />
  </dialog>
</template>

<style scoped>
.character-directory-scroll {
  scrollbar-width: none;
  overscroll-behavior: contain;
}
.character-directory-scroll::-webkit-scrollbar {
  display: none;
}
</style>
