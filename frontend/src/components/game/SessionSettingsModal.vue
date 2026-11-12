<script setup lang="ts">
import { ref, onMounted } from 'vue'
import SessionSettingsFrame from './SessionSettingsFrame.vue'
import SessionMemorySettings from './SessionMemorySettings.vue'
import VnNarrationSettings from './VnNarrationSettings.vue'
import SessionContentSettings from './SessionContentSettings.vue'
import DynamicLocationSettings from './DynamicLocationSettings.vue'
import StoryVisualPresets from '../editor/StoryVisualPresets.vue'
import LivingWorldSettings from './LivingWorldSettings.vue'
import ChpmSettings from './ChpmSettings.vue'
import SessionPortraitSettings from './SessionPortraitSettings.vue'
import NarratorSettings from './NarratorSettings.vue'

const props = defineProps<{
  sessionId?: string
  mode?: string
  initialTurns?: number
  initialCompression?: boolean
  initialAutoSpeakNarration?: boolean
  initialAutoSpeakDialogues?: boolean
  isSaving?: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (
    e: 'save',
    payload: {
      turns: number
      enableCompression: boolean
      autoSpeakNarration: boolean
      autoSpeakDialogues: boolean
    }
  ): void
}>()

const section = ref<'story' | 'memory' | 'characters'>('story')
const frame = ref<InstanceType<typeof SessionSettingsFrame> | null>(null)
async function showFailure(value: 'story' | 'characters') {
  section.value = value
  await frame.value?.revealErrors()
}

const narrator = ref<InstanceType<typeof NarratorSettings> | null>(null)
const vnNarration = ref<InstanceType<typeof VnNarrationSettings> | null>(null)
const contentSettings = ref<InstanceType<typeof SessionContentSettings> | null>(null)
const exploration = ref<InstanceType<typeof DynamicLocationSettings> | null>(null)
const visualPresets = ref<InstanceType<typeof StoryVisualPresets> | null>(null)
const livingWorld = ref<InstanceType<typeof LivingWorldSettings> | null>(null)
const portraitSettings = ref<InstanceType<typeof SessionPortraitSettings> | null>(null)
const chpm = ref<InstanceType<typeof ChpmSettings> | null>(null)
const savingExploration = ref(false)
async function saveAll(): Promise<void> {
  if (savingExploration.value || props.isSaving) return
  savingExploration.value = true
  try {
    if (contentSettings.value && !(await contentSettings.value.save())) {
      await showFailure('story')
      return
    }
    if (vnNarration.value && !(await vnNarration.value.save())) {
      await showFailure('story')
      return
    }
    if (narrator.value && !(await narrator.value.save())) {
      await showFailure('story')
      return
    }
    if (exploration.value && !(await exploration.value.save())) {
      await showFailure('story')
      return
    }
    if (livingWorld.value && !(await livingWorld.value.save())) {
      await showFailure('characters')
      return
    }
    if (portraitSettings.value && !(await portraitSettings.value.save())) {
      await showFailure('characters')
      return
    }
    if (chpm.value && !(await chpm.value.save())) {
      await showFailure('characters')
      return
    }
    if (visualPresets.value && !(await visualPresets.value.save())) {
      await showFailure('story')
      return
    }
    emit('save', {
      turns: turns.value,
      enableCompression: enableCompression.value,
      autoSpeakNarration: autoSpeakNarration.value,
      autoSpeakDialogues: autoSpeakDialogues.value
    })
  } finally {
    savingExploration.value = false
  }
}

const turns = ref(10)
const enableCompression = ref(true)
const autoSpeakNarration = ref(true)
const autoSpeakDialogues = ref(true)

onMounted(() => {
  if (typeof props.initialTurns === 'number' && props.initialTurns >= 1) {
    turns.value = Math.min(100, Math.max(1, props.initialTurns))
  }
  if (typeof props.initialCompression === 'boolean') {
    enableCompression.value = props.initialCompression
  }
  if (typeof props.initialAutoSpeakNarration === 'boolean') {
    autoSpeakNarration.value = props.initialAutoSpeakNarration
  }
  if (typeof props.initialAutoSpeakDialogues === 'boolean') {
    autoSpeakDialogues.value = props.initialAutoSpeakDialogues
  }
})
</script>

<template>
  <SessionSettingsFrame
    ref="frame"
    v-model:section="section"
    :saving="props.isSaving || savingExploration"
    @close="emit('close')"
    @save="saveAll"
  >
    <template #story>
      <VnNarrationSettings
        v-if="sessionId && mode === 'vn'"
        ref="vnNarration"
        :session-id="sessionId"
        class="settings-widget"
      />
      <NarratorSettings
        v-if="sessionId"
        ref="narrator"
        :endpoint="`/adventures/${encodeURIComponent(sessionId)}/narrator-settings`"
        class="settings-widget"
      />
      <SessionContentSettings
        v-if="sessionId"
        ref="contentSettings"
        :session-id="sessionId"
        class="settings-widget"
      />
      <DynamicLocationSettings
        v-if="sessionId"
        ref="exploration"
        :session-id="sessionId"
        :embedded="true"
        class="settings-widget"
      />
      <StoryVisualPresets
        v-if="sessionId"
        ref="visualPresets"
        :adventure-id="sessionId"
        session
        embedded
        class="settings-widget"
      />
    </template>
    <template #memory>
      <SessionMemorySettings
        v-model:turns="turns"
        v-model:enable-compression="enableCompression"
        v-model:auto-speak-narration="autoSpeakNarration"
        v-model:auto-speak-dialogues="autoSpeakDialogues"
      />
    </template>
    <template #characters>
      <LivingWorldSettings
        v-if="sessionId"
        ref="livingWorld"
        :session-id="sessionId"
        class="settings-widget"
      />
      <SessionPortraitSettings
        v-if="sessionId"
        ref="portraitSettings"
        :session-id="sessionId"
        class="settings-widget"
      />
      <ChpmSettings
        v-if="sessionId && mode === 'vn'"
        ref="chpm"
        :session-id="sessionId"
        class="settings-widget"
      />
      <p v-else class="text-xs leading-relaxed text-slate-400">
        NPC Personality is available in Visual Novel sessions.
      </p>
      <p class="mt-5 text-xs leading-relaxed text-slate-500">
        Changes apply to future actions. Existing replies and images are kept.
      </p>
    </template>
  </SessionSettingsFrame>
</template>
