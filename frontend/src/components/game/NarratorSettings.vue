<script setup lang="ts">
import { computed } from 'vue'
import { BookOpen, Save } from 'lucide-vue-next'
import { useNarratorSettings, VERBOSITY_OPTIONS } from '@/composables/useNarratorSettings'

const props = defineProps<{ endpoint: string; authorDefaults?: boolean }>()
const { settings, voices, loaded, busy, error, dirty, load, save, selectVoice } = useNarratorSettings(() => props.endpoint)
const selected = computed(() => settings.value.voice?.id ?? '')
const valid = computed(() => !settings.value.voice || (
  settings.value.voice.name.trim().length > 0 && settings.value.voice.instruction.trim().length > 0
))
defineExpose({ save: () => valid.value ? save() : Promise.resolve(false) })
</script>

<template>
  <section class="space-y-3 rounded-2xl border border-indigo-400/20 bg-indigo-950/15 p-4">
    <h4 class="flex items-center gap-2 text-xs font-black uppercase tracking-widest text-indigo-200">
      <BookOpen class="h-4 w-4" /> Narrator style
    </h4>
    <p class="text-xs text-slate-400">
      Literary voice changes the narrator's wording. Characters keep their own voices and personalities.
      {{ authorDefaults ? 'These defaults apply to new sessions.' : 'Changes apply to this session only.' }}
    </p>
    <p v-if="error" role="alert" class="text-xs text-rose-300">
      {{ error }} <button type="button" class="underline" :disabled="busy" @click="load">Reload</button>
    </p>
    <fieldset :disabled="!loaded || busy" class="space-y-3 disabled:opacity-60">
      <label class="block space-y-1 text-xs text-slate-300">
        <span>Literary voice</span>
        <select aria-label="Literary voice" :value="selected" class="w-full rounded-xl border border-white/10 bg-slate-900 p-2" @change="selectVoice(($event.target as HTMLSelectElement).value)">
          <option value="">Current narration</option>
          <option v-for="voice in voices" :key="voice.id" :value="voice.id">{{ voice.name }}</option>
          <option v-if="settings.voice && settings.voice.id !== 'custom' && !voices.some(voice => voice.id === settings.voice?.id)" :value="settings.voice.id">Saved: {{ settings.voice.name }}</option>
          <option value="custom">Custom narrator</option>
        </select>
      </label>
      <template v-if="settings.voice?.id === 'custom'">
        <label class="block space-y-1 text-xs text-slate-300">
          <span>Name</span>
          <input v-model="settings.voice.name" maxlength="80" class="w-full rounded-xl border border-white/10 bg-slate-900 p-2" />
        </label>
        <label class="block space-y-1 text-xs text-slate-300">
          <span>Wording and rhythm</span>
          <textarea v-model="settings.voice.instruction" maxlength="1500" rows="4" placeholder="Describe diction, imagery and sentence rhythm." class="w-full rounded-xl border border-white/10 bg-slate-900 p-2" />
        </label>
        <p v-if="!valid" class="text-xs text-amber-300">Enter a name and a style instruction before saving.</p>
      </template>
      <template v-else-if="settings.voice">
        <p class="text-xs text-slate-400">{{ settings.voice.description }}</p>
        <blockquote v-if="settings.voice.sample" class="border-l-2 border-indigo-400/40 pl-3 text-xs italic leading-relaxed text-slate-300">{{ settings.voice.sample }}</blockquote>
      </template>
      <label class="block space-y-1 text-xs text-slate-300">
        <span>Amount of narration</span>
        <select v-model="settings.verbosity" aria-label="Amount of narration" class="w-full rounded-xl border border-white/10 bg-slate-900 p-2">
          <option v-for="[value, label] in VERBOSITY_OPTIONS" :key="value" :value="value">{{ label }}</option>
        </select>
      </label>
      <p class="text-xs text-slate-500">Scene pacing controls events. This preference controls prose detail and adds no model calls.</p>
    </fieldset>
    <button v-if="authorDefaults" type="button" :disabled="!dirty || busy || !valid" class="flex items-center gap-2 rounded-xl bg-indigo-600 px-4 py-2 text-xs font-bold text-white transition hover:bg-indigo-500 disabled:opacity-40" @click="save">
      <Save class="h-4 w-4" /> {{ busy ? 'Saving…' : 'Save narrator defaults' }}
    </button>
  </section>
</template>
