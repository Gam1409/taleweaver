<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  BookOpenText,
  History,
  LogOut,
  Map as MapIcon,
  SlidersHorizontal,
  Terminal,
  Volume2,
  VolumeX
} from 'lucide-vue-next'
import { configState } from '@/store/config'
import { audioService } from '@/services/audioService'
import BableFishSelector from '../BableFishSelector.vue'
import ActionGroupMenu from './ActionGroupMenu.vue'

const props = defineProps<{ debugMode?: boolean; sessionId?: string }>()
const emit = defineEmits<{
  openChronicles: []
  openSettings: []
  openWorldInfo: []
  openDebug: []
  toggleMobileInteract: []
  exitSession: []
}>()
const open = ref(false)
watch(
  () => props.sessionId,
  () => {
    open.value = false
  }
)
</script>

<template>
  <div class="header-session-controls">
    <button
      v-if="configState.isTtsEnabled && audioService.isPlaying.value"
      type="button"
      class="header-stop-speech"
      title="Stop Speech (SPACE)"
      aria-label="Stop speech"
      @click="audioService.stop()"
    >
      <VolumeX aria-hidden="true" />
    </button>
    <BableFishSelector subtle />
    <div class="header-session-menu">
      <ActionGroupMenu v-model="open" label="Session" :icon="SlidersHorizontal">
        <button type="button" role="menuitem" class="action-menu-item" @click="emit('openWorldInfo')">
          <BookOpenText class="text-amber-300" aria-hidden="true" /><span class="action-menu-copy"><span class="action-menu-title">World Info</span><span class="action-menu-description">Knowledge for this session</span></span>
        </button>
        <button
          type="button"
          role="menuitem"
          class="action-menu-item"
          @click="emit('openSettings')"
        >
          <SlidersHorizontal class="text-amber-300" aria-hidden="true" /><span
            class="action-menu-copy"
            ><span class="action-menu-title">Session settings</span
            ><span class="action-menu-description">Memory, narration and preferences</span></span
          >
        </button>
        <button
          type="button"
          role="menuitem"
          class="action-menu-item"
          @click="emit('openChronicles')"
        >
          <History class="text-indigo-300" aria-hidden="true" /><span class="action-menu-copy"
            ><span class="action-menu-title">Chronicles</span
            ><span class="action-menu-description">Timeline and saved checkpoints</span></span
          >
        </button>
        <button
          v-if="configState.isTtsEnabled"
          type="button"
          role="menuitem"
          class="action-menu-item"
          @click="audioService.toggleAutoSpeech()"
        >
          <Volume2 class="text-amber-300" aria-hidden="true" /><span class="action-menu-copy"
            ><span class="action-menu-title"
              >Auto-narration {{ audioService.autoSpeechEnabled.value ? 'on' : 'off' }}</span
            ><span class="action-menu-description">Read new replies aloud</span></span
          >
        </button>
        <button
          v-if="debugMode"
          type="button"
          role="menuitem"
          class="action-menu-item"
          @click="emit('openDebug')"
        >
          <Terminal class="text-cyan-300" aria-hidden="true" /><span class="action-menu-copy"
            ><span class="action-menu-title">Debug inspector</span
            ><span class="action-menu-description">Debug mode is active</span></span
          >
        </button>
        <button type="button" role="menuitem" class="action-menu-item" @click="emit('exitSession')">
          <LogOut class="text-rose-300" aria-hidden="true" /><span class="action-menu-copy"
            ><span class="action-menu-title">Exit session</span
            ><span class="action-menu-description">Return to the portal</span></span
          >
        </button>
      </ActionGroupMenu>
    </div>
    <button
      type="button"
      class="header-interact md:hidden"
      title="Toggle Interact Menu"
      aria-label="Toggle interact menu"
      @click="emit('toggleMobileInteract')"
    >
      <MapIcon aria-hidden="true" />
    </button>
  </div>
</template>

<style scoped>
.header-session-controls {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
}
.header-session-menu :deep(.action-group-trigger) {
  min-height: 36px;
  font:
    11px -apple-system,
    BlinkMacSystemFont,
    'Segoe UI',
    sans-serif;
  border-color: rgb(100 116 139 / 0.25);
  padding: 6px 9px;
  background: rgb(15 23 42 / 0.3);
}
.header-session-menu :deep(.action-group-trigger:hover),
.header-session-menu :deep(.action-group-trigger.is-open) {
  border-color: rgb(251 191 36 / 0.35);
  background: rgb(251 191 36 / 0.07);
}
.header-stop-speech,
.header-interact {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  border: 1px solid rgb(100 116 139 / 0.25);
  border-radius: 9px;
  background: rgb(15 23 42 / 0.3);
  color: #c8ac72;
}
.header-stop-speech {
  color: #fda4af;
  border-color: rgb(251 113 133 / 0.3);
}
.header-stop-speech > svg,
.header-interact > svg {
  width: 16px;
  height: 16px;
  stroke-width: 1.6;
}
.header-stop-speech:hover,
.header-interact:hover {
  background: rgb(148 163 184 / 0.08);
}
@media (min-width: 768px) {
  .header-interact {
    display: none;
  }
}
@media (max-width: 700px) {
  .header-session-controls {
    gap: 4px;
  }
  .header-session-menu :deep(.action-group-trigger) {
    min-height: 40px;
    font-size: 10px;
    padding: 5px 6px;
    gap: 4px;
  }
  .header-stop-speech,
  .header-interact {
    width: 34px;
    height: 40px;
  }
  .header-session-controls :deep(.bable-fish-container > button) {
    width: 34px;
    height: 40px;
  }
}
</style>
