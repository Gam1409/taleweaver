<script setup lang="ts">
import LivingWorldAdventureButton from '@/components/living-world/LivingWorldAdventureButton.vue'
import NpcPersonalityDefaults from '@/components/living-world/NpcPersonalityDefaults.vue'
import type { LivingWorldPreferences } from '@/services/livingWorld'
import type { ChpmSettings } from '@/composables/useChpmSettings'

defineProps<{
  livingWorld?: LivingWorldPreferences | null
  personality?: ChpmSettings | null
  characters: { id: string; name: string }[]
  isVn: boolean
  busy: boolean
}>()
const emit = defineEmits<{
  'update:livingWorld': [value: LivingWorldPreferences]
  'update:personality': [value: ChpmSettings]
  save: []
}>()
</script>

<template>
  <section class="space-y-6">
    <header>
      <h2 class="text-2xl font-bold text-white">Living World</h2>
      <p class="mt-2 text-sm text-slate-400">
        Concordia and NPC Personality defaults for new sessions.
      </p>
    </header>
    <p v-if="!isVn" class="rounded-xl border border-amber-400/20 p-4 text-sm text-amber-200">
      These features run in Visual Novel mode. You can prepare defaults here; other modes keep
      standard behavior.
    </p>
    <fieldset :disabled="busy" class="space-y-6 disabled:opacity-60">
      <section class="space-y-3 rounded-2xl border border-teal-400/20 bg-slate-950/40 p-5">
        <h3 class="text-lg font-bold text-teal-200">Concordia</h3>
        <p class="text-sm text-slate-400">
          Background routines, private decisions and catch-up while away. Configure the optional
          engine and its limits.
        </p>
        <LivingWorldAdventureButton
          :model-value="livingWorld"
          @update:model-value="emit('update:livingWorld', $event)"
        />
      </section>
      <NpcPersonalityDefaults
        :model-value="personality"
        :characters="characters"
        @update:model-value="emit('update:personality', $event)"
      />
      <p
        v-if="personality?.mode === 'live' && livingWorld?.deliberation_enabled"
        role="alert"
        class="text-sm text-amber-200"
      >
        Both systems cannot make private NPC decisions together. Disable Concordia private decisions
        or select Standard / Observe for NPC Personality before saving.
      </p>
      <button
        type="button"
        class="rounded-xl bg-cyan-500 px-5 py-3 text-sm font-bold text-slate-950 disabled:opacity-40"
        :disabled="busy"
        @click="emit('save')"
      >
        {{ busy ? 'Saving…' : 'Save adventure defaults' }}
      </button>
    </fieldset>
  </section>
</template>
