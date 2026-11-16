<script setup lang="ts">
import type { NpcCard } from '@/composables/useNpcJournal'
import type { PortraitOptions, PortraitTarget } from '@/composables/useSessionPortrait'
import SessionCharactersModal from './SessionCharactersModal.vue'
import NpcPortraitModal from './NpcPortraitModal.vue'

defineProps<{
  sessionId: string
  directoryOpen: boolean
  npc: PortraitTarget | null
  stateRevision?: unknown
  busy: boolean
  error: string
  updated: boolean
  refined?: boolean
}>()
const emit = defineEmits<{
  closeDirectory: []
  select: [npc: NpcCard]
  closeCard: []
  generate: [options: PortraitOptions]
}>()
</script>

<template>
  <SessionCharactersModal
    v-if="directoryOpen && !npc"
    :session-id="sessionId"
    @close="emit('closeDirectory')"
    @select="emit('select', $event)"
  />
  <NpcPortraitModal
    v-if="npc"
    :session-id="sessionId"
    :npc="npc"
    :refined="refined"
    :state-revision="stateRevision"
    :busy="busy"
    :error="error"
    :updated="updated"
    @close="emit('closeCard')"
    @generate="emit('generate', $event)"
  />
</template>
