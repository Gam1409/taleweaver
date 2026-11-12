<script setup lang="ts">
import { Sparkles } from 'lucide-vue-next'
import GameClockWidget from '../GameClockWidget.vue'
import HeaderStoryContext from './HeaderStoryContext.vue'
import HeaderSessionControls from './HeaderSessionControls.vue'

const props = defineProps<{
  sceneName?: string | null
  activeSequence?: any | null
  adventureTitle?: string | null
  creator?: string | null
  copyright?: string | null
  trackedQuest?: any
  gameTime?: { dateShort: string; time: string } | null
  clockTick?: boolean
  exp?: number
  mode?: 'rpg' | 'story' | 'chat' | 'vn'
  debugMode?: boolean
  systemDebugEnabled?: boolean
  sessionId?: string
}>()
const emit = defineEmits<{
  openChronicles: []
  openQuests: []
  openSettings: []
  openDebug: []
  toggleMobileInteract: []
  exitSession: []
}>()
</script>

<template>
  <header class="game-header">
    <HeaderStoryContext
      class="game-header-title"
      :scene-name="sceneName"
      :active-sequence="activeSequence"
      :adventure-title="adventureTitle"
      :creator="creator"
      :copyright="copyright"
      :tracked-quest="trackedQuest"
      :mode="mode"
      :debug-mode="debugMode"
      :system-debug-enabled="systemDebugEnabled"
      :session-id="sessionId"
      @open-quests="emit('openQuests')"
    />
    <div v-if="gameTime || mode !== 'vn'" class="header-metrics" aria-label="Session progress">
      <GameClockWidget
        :game-time="props.gameTime || null"
        :clock-tick="props.clockTick || false"
        compact
      />
      <div
        v-if="mode !== 'vn'"
        class="header-experience"
        :class="{ 'has-clock': gameTime }"
        title="Experience Points (XP)"
      >
        <Sparkles aria-hidden="true" /><span>{{ exp ?? 0 }} <small>XP</small></span>
      </div>
    </div>
    <HeaderSessionControls
      class="game-header-controls"
      :debug-mode="debugMode"
      :session-id="sessionId"
      @open-chronicles="emit('openChronicles')"
      @open-settings="emit('openSettings')"
      @open-debug="emit('openDebug')"
      @toggle-mobile-interact="emit('toggleMobileInteract')"
      @exit-session="emit('exitSession')"
    />
  </header>
</template>

<style scoped>
.game-header {
  position: relative;
  z-index: 20;
  flex-shrink: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 22px;
  padding: 15px 24px;
  background: rgb(2 6 23 / 0.8);
  backdrop-filter: blur(16px);
  border-bottom: 1px solid rgb(51 65 85 / 0.55);
}
.game-header-title {
  min-width: 0;
}
.header-metrics {
  display: flex;
  flex-wrap: wrap;
  max-width: 100%;
  row-gap: 7px;
  align-items: center;
  gap: 18px;
  flex-shrink: 0;
  min-width: 0;
}
.header-experience {
  display: flex;
  align-items: center;
  gap: 7px;
  font:
    600 13px/1.5 -apple-system,
    BlinkMacSystemFont,
    'Segoe UI',
    sans-serif;
  color: #dec28a;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.header-experience.has-clock {
  border-left: 1px solid rgb(100 116 139 / 0.3);
  padding-left: 18px;
}
.header-experience > svg {
  width: 15px;
  height: 15px;
  stroke-width: 1.5;
  color: #a58b5e;
}
.header-experience small {
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.05em;
  color: #8d9bae;
}
.game-header-controls {
  grid-column: 3;
  border-left: 1px solid rgb(100 116 139 / 0.25);
  padding-left: 18px;
}
@media (max-width: 900px) {
  .game-header {
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 10px 14px;
    padding: 12px 16px;
  }
  .game-header-title {
    grid-column: 1;
    grid-row: 1/3;
  }
  .game-header-controls {
    grid-column: 2;
    grid-row: 1;
    padding-left: 0;
    border-left: 0;
    justify-self: end;
  }
  .header-metrics {
    grid-column: 2;
    grid-row: 2;
    justify-self: end;
    gap: 12px;
  }
  .header-experience.has-clock {
    padding-left: 12px;
  }
  .header-experience {
    font-size: 12px;
  }
}
@media (max-width: 520px) {
  .game-header {
    gap: 5px 10px;
    padding: 8px 12px;
  }
  .game-header-title {
    grid-column: 1/-1;
    grid-row: 1;
    min-height: 0;
  }
  .game-header-controls {
    grid-column: 2;
    grid-row: 2;
  }
  .header-metrics {
    grid-column: 1;
    grid-row: 2;
    justify-self: start;
    gap: 12px;
  }
  .header-experience.has-clock {
    padding-left: 12px;
  }
  .header-experience > svg {
    display: none;
  }
}
</style>
