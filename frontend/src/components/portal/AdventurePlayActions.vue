<script setup lang="ts">
import { computed } from 'vue'
import { Loader2, Play, Plus, RefreshCw, Wrench } from 'lucide-vue-next'
import type { AdventureTemplateSummary, GameSession } from '@/types'

const props = defineProps<{
  template: AdventureTemplateSummary
  resumeSession?: GameSession
  isStartingSession?: boolean
  isStartingThisTemplate?: boolean
  isResuming?: boolean
  isUpdating?: boolean
  compact?: boolean
}>()

defineEmits<{
  (e: 'resume', gameId: string): void
  (e: 'start-session', templateId: string): void
  (e: 'update-adventure', templateId: string): void
  (e: 'migrate', template: AdventureTemplateSummary): void
}>()

const needsMigration = computed(() => props.template.is_legacy_format || !props.template.can_start)
const resumeTitle = computed(() => {
  const scene = props.resumeSession?.current_scene_name
  return `Continue saved progress${scene ? ` at ${scene}` : ''}. Other saves are available in Sessions.`
})
const buttonSize = computed(() =>
  props.compact ? 'px-3 py-1.5 text-xs' : 'w-full py-2 sm:py-3.5 text-[10px] sm:text-xs'
)
</script>

<template>
  <div class="flex flex-col gap-1.5 min-w-0">
    <button
      v-if="resumeSession"
      type="button"
      :disabled="isStartingSession"
      :title="resumeTitle"
      :class="buttonSize"
      class="rounded-xl border border-emerald-500/30 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25 font-black uppercase tracking-wider flex items-center justify-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
      @click="$emit('resume', resumeSession.game_id)"
    >
      <Loader2
        v-if="isStartingThisTemplate && isResuming"
        class="w-3.5 h-3.5 animate-spin shrink-0"
      />
      <Play v-else class="w-3.5 h-3.5 shrink-0" />
      {{ isStartingThisTemplate && isResuming ? 'Resuming...' : 'Resume' }}
    </button>

    <button
      v-if="needsMigration"
      type="button"
      :disabled="isStartingSession || isUpdating"
      :class="buttonSize"
      class="rounded-xl border border-amber-500/30 bg-amber-500/15 text-amber-300 hover:bg-amber-500/25 font-bold uppercase tracking-wider flex items-center justify-center gap-1.5 disabled:opacity-50"
      @click="
        template.has_update
          ? $emit('update-adventure', template.template_id)
          : $emit('migrate', template)
      "
    >
      <Loader2 v-if="isUpdating" class="w-3.5 h-3.5 animate-spin shrink-0" />
      <RefreshCw v-else-if="template.has_update" class="w-3.5 h-3.5 shrink-0" />
      <Wrench v-else class="w-3.5 h-3.5 shrink-0" />
      {{
        isUpdating ? 'Updating...' : template.has_update ? 'Update to Play' : 'Migrate Adventure'
      }}
    </button>
    <button
      v-else
      type="button"
      :disabled="isStartingSession"
      :title="
        resumeSession
          ? 'Start a separate session. Your saved progress is kept.'
          : 'Start a new adventure session'
      "
      :class="[
        buttonSize,
        resumeSession
          ? 'border-white/10 text-slate-400 hover:text-white hover:bg-white/5'
          : 'border-emerald-500/30 bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25'
      ]"
      class="rounded-xl border font-bold uppercase tracking-wider flex items-center justify-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
      @click="$emit('start-session', template.template_id)"
    >
      <Loader2
        v-if="isStartingThisTemplate && !isResuming"
        class="w-3.5 h-3.5 animate-spin shrink-0"
      />
      <Plus v-else-if="resumeSession" class="w-3.5 h-3.5 shrink-0" />
      <Play v-else class="w-3.5 h-3.5 shrink-0" />
      {{
        isStartingThisTemplate && !isResuming
          ? 'Starting...'
          : resumeSession
            ? 'New session'
            : 'Start'
      }}
    </button>
  </div>
</template>
