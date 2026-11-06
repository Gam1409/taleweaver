<script setup lang="ts">
/**
 * ImmersiveCharacterStage — Left-side 2:3 vertical character cards
 *
 * Displays portraits of the protagonist and scene NPCs with active speaker auras,
 * health status, defeat tags, and quick click/hover interactions.
 */
import { ref, watch, nextTick, computed } from 'vue'
import { getImageUrl, getOriginalImageUrl } from '@/utils/game_icons'
import NpcThoughtBubble from './NpcThoughtBubble.vue'
import { DEFAULT_PORTRAIT_PREFERENCES, emotionLabel, portraitStyle, thoughtText, type PortraitCue, type PortraitPreferences } from '@/utils/npcPresentation'
import { ImagePlus } from 'lucide-vue-next'
import type { PortraitTarget } from '@/composables/useSessionPortrait'

const props = defineProps<{
  mode?: string
  npcs: any[]
  activeSpeakers: Set<string>
  activeTurnIndex?: number
  portraitCues?: Record<string, PortraitCue>
  portraitPreferences?: PortraitPreferences
}>()

const emit = defineEmits<{
  npcClick: [npc: any]
  npcHover: [entity: any, event: MouseEvent]
  npcLeave: []
  npcContextmenu: [npc: any, event: MouseEvent]
  portrait: [npc: PortraitTarget]
}>()

const preferences = computed(() => props.portraitPreferences || DEFAULT_PORTRAIT_PREFERENCES)
const paletteActive = computed(() => preferences.value.emotion_palette && preferences.value.brightness > 0)
const thought = ref({ id: '', name: '', text: '', anchor: null as HTMLElement | null })
function closeThought() { thought.value = { id: '', name: '', text: '', anchor: null } }
function showThought(npc: any, event: MouseEvent | FocusEvent) {
  const useThought = preferences.value.character_thoughts && npc.id !== 'PLAYER'
  if (!useThought) {
    closeThought()
    if (event instanceof MouseEvent) emit('npcHover', npc, event)
    return
  }
  emit('npcLeave')
  const text = thoughtText(props.portraitCues?.[npc.id], preferences.value)
  if (!text) { closeThought(); return }
  thought.value = { id: npc.id, name: npc.name, text, anchor: event.currentTarget as HTMLElement }
}
function onMove(npc: any, event: MouseEvent) {
  if (!preferences.value.character_thoughts || npc.id === 'PLAYER') emit('npcHover', npc, event)
}
function onClick(npc: any) {
  closeThought()
  emit('npcLeave')
  if (preferences.value.character_thoughts && npc.id !== 'PLAYER') {
    emit('portrait', npc)
    return
  }
  emit('npcClick', npc)
}
function onKeydown(npc: any, event: KeyboardEvent) {
  if (event.target !== event.currentTarget) return
  if (event.key === 'Escape') closeThought()
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    onClick(npc)
  }
}
function onLeave() { closeThought(); emit('npcLeave') }
watch([() => props.activeTurnIndex, () => props.portraitCues, preferences], closeThought)

const stageContainerRef = ref<HTMLElement | null>(null)
const brokenImages = ref<Record<string, boolean>>({})

function scrollToTop() {
  if (!stageContainerRef.value) return
  stageContainerRef.value.scrollTo({
    top: 0,
    left: 0,
    behavior: 'smooth'
  })
}

const activeSpeakersSignature = computed(() => {
  if (!props.activeSpeakers || props.activeSpeakers.size === 0) return ''
  return Array.from(props.activeSpeakers).sort().join(',')
})

const hasSpeakingNpc = computed(() => {
  if (!props.activeSpeakers || props.activeSpeakers.size === 0) return false
  return (props.npcs || []).some((npc) => isNpcSpeaking(npc))
})

watch(
  [() => props.activeTurnIndex, activeSpeakersSignature],
  () => {
    if (hasSpeakingNpc.value) {
      nextTick(() => {
        scrollToTop()
      })
    }
  }
)

function handleImageError(path?: string | null) {
  if (!path) return
  brokenImages.value[path] = true
}

function onImageLoadError(e: Event, path?: string | null) {
  if (!path) return
  const target = e.target as HTMLImageElement
  if (target && target.src && target.src.includes('_thumb')) {
    target.src = getOriginalImageUrl(path)
  } else {
    handleImageError(path)
  }
}

function showImage(path?: string | null) {
  return !!path && !brokenImages.value[path]
}

function isNpcSpeaking(npc: any): boolean {
  if (!npc || !props.activeSpeakers) return false
  const nameMatch = npc.name && props.activeSpeakers.has(npc.name.toLowerCase())
  const idMatch = npc.id && props.activeSpeakers.has(String(npc.id).toLowerCase())
  return Boolean(nameMatch || idMatch)
}
</script>

<template>
  <aside
    ref="stageContainerRef"
    class="game-character-stage flex gap-2 shrink-0 overflow-x-auto sm:overflow-x-hidden sm:overflow-y-auto w-full sm:w-28 md:w-36 lg:w-44 custom-scrollbar sm:pr-1 py-1 max-h-24 sm:max-h-full"
    :class="{ 'emotion-stage': paletteActive }"
  >
    <TransitionGroup name="npc-stage" tag="div" class="flex flex-row sm:flex-col gap-2 w-max sm:w-full">
      <div
        v-for="npc in props.npcs"
        :key="npc.id"
        class="emotion-portrait relative group flex flex-col items-center bg-slate-950 rounded-xl border-2 transition-all duration-300 shrink-0 w-14 sm:w-full aspect-[2/3] overflow-hidden cursor-pointer shadow-[0_6px_20px_rgba(0,0,0,0.7)] active:scale-98"
        :class="[
          isNpcSpeaking(npc) && !emotionLabel(props.portraitCues?.[npc.id], preferences)
            ? 'border-amber-400 shadow-[0_0_25px_rgba(251,191,36,0.6)] ring-2 ring-amber-400/60'
            : npc.id === 'PLAYER'
              ? 'border-emerald-500/70 hover:border-emerald-400'
              : 'border-slate-700/70 hover:border-cyan-400/80'
        ]"
        tabindex="0"
        :aria-label="[npc.name, emotionLabel(props.portraitCues?.[npc.id], preferences)].filter(Boolean).join(' · ')"
        :aria-describedby="thought.id === npc.id ? 'npc-current-thought' : undefined"
        :title="!preferences.character_thoughts ? emotionLabel(props.portraitCues?.[npc.id], preferences) || undefined : undefined"
        :style="npc.id !== 'PLAYER' ? portraitStyle(props.portraitCues?.[npc.id], preferences) : {}"
        @click="onClick(npc)"
        @keydown="onKeydown(npc, $event)"
        @focusin.self="showThought(npc, $event)"
        @focusout="closeThought"
        @mouseenter="showThought(npc, $event)"
        @mousemove="onMove(npc, $event)"
        @mouseleave="onLeave"
        @contextmenu.prevent="emit('npcContextmenu', npc, $event)"
      >
        <!-- Full 2:3 Character Portrait -->
        <img
          v-if="npc.image_url && showImage(npc.image_url)"
          :src="getImageUrl(npc.image_url, { thumbnail: true })"
          :alt="npc.name"
          class="w-full h-full object-cover object-top transition-transform duration-700 group-hover:scale-105"
          :class="{ 'grayscale opacity-50': props.mode !== 'vn' && (npc.is_defeated || npc.hp === 0) }"
          @error="onImageLoadError($event, npc.image_url)"
        />
        <div v-else class="w-full h-full flex flex-col items-center justify-center bg-gradient-to-b from-slate-900 to-slate-950 text-slate-600">
          <i :class="['ra text-4xl mb-1', npc.id === 'PLAYER' ? 'ra-player text-emerald-400' : 'ra-helmet text-cyan-400']"></i>
        </div>

        <!-- Active Speaker Badge -->
        <button
          v-if="npc.id && npc.id !== 'PLAYER'"
          type="button"
          class="absolute top-1 left-1 z-30 p-1.5 rounded-lg bg-slate-950/85 text-slate-200 border border-white/20 hover:bg-slate-700 hover:text-white focus-visible:ring-2 focus-visible:ring-amber-400"
          :aria-label="`Change portrait of ${npc.name}`"
          title="Generate or replace this NPC's portrait"
          @click.stop="emit('portrait', npc)"
          @mouseenter.stop="emit('npcLeave')"
          @mousemove.stop
          @contextmenu.stop.prevent
        >
          <ImagePlus class="w-3.5 h-3.5" />
        </button>

        <div v-if="isNpcSpeaking(npc)" class="absolute top-2 right-2 z-20 px-1.5 py-0.5 rounded-full bg-amber-500 text-black text-[8px] font-black uppercase tracking-wider shadow-md animate-bounce">
          Speaking
        </div>

        <!-- Hero Tag for Player -->
        <div v-else-if="npc.id === 'PLAYER'" class="absolute top-2 left-2 z-20 px-1.5 py-0.5 rounded-full bg-emerald-500/80 text-white backdrop-blur-md border border-emerald-300/40 text-[8px] font-black uppercase tracking-wider shadow-md">
          You
        </div>

        <!-- Defeated Ribbon -->
        <div v-if="props.mode !== 'vn' && (npc.is_defeated || npc.hp === 0)" class="absolute -right-6 top-3 bg-red-600 text-white text-[8px] font-black uppercase tracking-[0.12em] py-0.5 w-24 text-center rotate-45 shadow-lg z-20">
          Defeated
        </div>

        <!-- Name & Role Overlay with Gradient & Strong Shadow -->
        <div class="absolute inset-x-0 bottom-0 pt-8 pb-2 px-2 bg-gradient-to-t from-black/95 via-black/60 to-transparent flex flex-col items-center text-center pointer-events-none z-10">
          <h4 class="text-[11px] sm:text-xs font-black text-white group-hover:text-amber-300 transition-colors uppercase tracking-wider drop-shadow-[0_2px_3px_rgba(0,0,0,1)] truncate w-full">
            {{ npc.name }}
          </h4>
          <span v-if="npc.role" class="text-[9px] font-bold text-slate-300/90 uppercase tracking-widest drop-shadow-[0_1px_2px_rgba(0,0,0,1)] truncate w-full mt-0.5">
            {{ npc.role }}
          </span>
        </div>
      </div>
    </TransitionGroup>
  </aside>
  <NpcThoughtBubble :text="thought.text" :name="thought.name" :anchor="thought.anchor" @dismiss="closeThought" />
</template>

<style scoped>
/* Reserve space inside the scrollport so the portrait's outer halo stays visible. */
.emotion-stage {
  padding: 0;
  max-height: 7.5rem;
}
.emotion-stage > div {
  gap: 1rem;
  padding: 12px;
  height: max-content;
}
@media (min-width: 640px) {
  .emotion-stage { width: calc(7rem + 1.5rem); max-height: 100%; }
}
@media (min-width: 768px) {
  .emotion-stage { width: calc(9rem + 1.5rem); }
}
@media (min-width: 1024px) {
  .emotion-stage { width: calc(11rem + 1.5rem); }
}

/* Keep the inner glow above the image, below names and controls. */
.emotion-portrait::after {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 9;
  pointer-events: none;
  border-radius: inherit;
  box-shadow: var(--portrait-inner-glow, none);
}

.custom-scrollbar::-webkit-scrollbar { width: 4px; }
.custom-scrollbar::-webkit-scrollbar-track { background: rgba(0,0,0,0.1); }
.custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.05); border-radius: 4px; }
.custom-scrollbar::-webkit-scrollbar-thumb:hover { background: rgba(255, 255, 255, 0.1); }

.npc-stage-move,
.npc-stage-enter-active,
.npc-stage-leave-active {
  transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
}
.npc-stage-enter-from,
.npc-stage-leave-to {
  opacity: 0;
  transform: scale(0.92);
}

.ra {
  font-family: 'rpgawesome' !important;
  display: inline-block;
  line-height: 1;
  vertical-align: middle;
}
</style>
