<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  Globe2,
  BookOpen,
  RefreshCw,
  SlidersHorizontal,
  Map as MapIcon,
  User,
  Users,
  Scroll,
  History,
  BrainCircuit,
  HelpCircle,
  Terminal
} from 'lucide-vue-next'
import ActionGroupMenu from './ActionGroupMenu.vue'
import ResponseActions from '../ResponseActions.vue'
import NarrationCorrectionButton from '../NarrationCorrectionButton.vue'

const props = defineProps<{
  gameId?: string
  isEvaluating?: boolean
  mode?: string
  inventory?: any[]
  trackedQuest?: any
  worldMemories?: any[]
  inventoryGlow?: boolean
  mapGlow?: boolean
  questGlow?: boolean
  debugMode?: boolean
}>()
const emit = defineEmits<{
  open: []
  openQuests: []
  openMap: []
  openSheet: []
  openChronicles: []
  openWalkthrough: []
  openMemories: []
  openCharacters: []
  openDebug: []
}>()
const active = ref<string | null>(null)
const groups = computed(() =>
  [
    {
      id: 'world',
      label: 'World',
      icon: Globe2,
      glow: props.inventoryGlow || props.mapGlow,
      items: [
        {
          event: 'openSheet',
          label: props.mode === 'vn' ? 'Profile & inventory' : 'Hero & inventory',
          description: 'Character details and belongings',
          icon: User,
          color: 'text-emerald-400',
          count: props.inventory?.length
        },
        {
          event: 'openMap',
          label: 'World map',
          description: 'Locations and connected paths',
          icon: MapIcon,
          color: 'text-sky-400'
        },
        {
          event: 'openCharacters',
          label: 'Characters',
          description: 'People you have met',
          icon: Users,
          color: 'text-amber-300'
        }
      ]
    },
    {
      id: 'story',
      label: 'Story',
      icon: BookOpen,
      glow: props.questGlow,
      items: [
        ...(props.mode === 'vn'
          ? []
          : [
              {
                event: 'openQuests',
                label: 'Quests',
                description: 'Objectives and tracked progress',
                icon: Scroll,
                color: 'text-amber-400',
                count: props.trackedQuest ? 1 : undefined
              }
            ]),
        {
          event: 'openChronicles',
          label: 'Chronicles',
          description: 'Timeline and saved checkpoints',
          icon: History,
          color: 'text-indigo-400'
        },
        {
          event: 'openMemories',
          label: 'World memories',
          description: 'Established facts about your story',
          icon: BrainCircuit,
          color: 'text-purple-400',
          count: props.worldMemories?.length
        }
      ]
    },
    { id: 'response', label: 'Response', icon: RefreshCw, glow: false, items: [] },
    {
      id: 'tools',
      label: 'Tools',
      icon: SlidersHorizontal,
      glow: false,
      items: [
        ...(props.mode === 'vn'
          ? []
          : [
              {
                event: 'openWalkthrough',
                label: 'Adventure hints',
                description: 'Guidance for the current adventure',
                icon: HelpCircle,
                color: 'text-amber-400'
              }
            ]),
        ...(props.debugMode
          ? [
              {
                event: 'openDebug',
                label: 'Debug inspector',
                description: 'Inspect the current session state',
                icon: Terminal,
                color: 'text-cyan-400'
              }
            ]
          : [])
      ]
    }
  ].filter(group => group.id === 'response' || group.items.length)
)

function close() {
  active.value = null
}
const navigation: Record<string, () => void> = {
  openQuests: () => emit('openQuests'),
  openMap: () => emit('openMap'),
  openSheet: () => emit('openSheet'),
  openChronicles: () => emit('openChronicles'),
  openWalkthrough: () => emit('openWalkthrough'),
  openMemories: () => emit('openMemories'),
  openCharacters: () => emit('openCharacters'),
  openDebug: () => emit('openDebug')
}
function navigate(event: string) {
  navigation[event]?.()
  close()
}
watch(active, value => {
  if (value) emit('open')
})
watch(() => [props.mode, props.debugMode, props.gameId], close)
defineExpose({ close })
</script>

<template>
  <div class="flex min-w-0 items-center gap-0.5 sm:gap-1" aria-label="Chat action groups">
    <ActionGroupMenu
      v-for="group in groups"
      :key="group.id"
      :label="group.label"
      :icon="group.icon"
      :glow="group.glow"
      :model-value="active === group.id"
      @update:model-value="active = $event ? group.id : null"
    >
      <template v-if="group.id === 'response'">
        <ResponseActions :game-id="gameId" :disabled="isEvaluating" menu />
        <NarrationCorrectionButton :game-id="gameId" menu />
      </template>
      <button
        v-for="item in group.items"
        :key="item.event"
        type="button"
        role="menuitem"
        class="action-menu-item"
        @click="navigate(item.event)"
      >
        <component :is="item.icon" :class="item.color" aria-hidden="true" />
        <span class="action-menu-copy"
          ><span class="action-menu-title">{{ item.label }}</span
          ><span class="action-menu-description">{{ item.description }}</span></span
        >
        <span
          v-if="item.count"
          class="rounded-full bg-amber-500/10 px-1.5 text-[10px] text-amber-200"
          >{{ item.count }}</span
        >
      </button>
    </ActionGroupMenu>
  </div>
</template>
