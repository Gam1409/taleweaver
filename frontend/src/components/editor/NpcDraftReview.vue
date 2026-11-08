<script setup lang="ts">
import type { NpcDraft } from '@/services/npcCreation'
import NpcDraftItems from './NpcDraftItems.vue'

const draft = defineModel<NpcDraft>({ required: true })
defineProps<{ selected: boolean[]; disabled: boolean }>()
const emit = defineEmits<{ (e: 'update:selected', value: boolean[]): void }>()
function setAge(event: Event) {
  const value = (event.target as HTMLInputElement).value
  draft.value.age_years = value === '' ? null : Number(value)
}
</script>

<template>
  <section aria-label="Review NPC draft" class="space-y-5 border-t border-emerald-500/20 pt-5">
    <h3 class="font-bold text-emerald-300">Review the new character</h3>
    <fieldset :disabled="disabled" class="grid gap-4 sm:grid-cols-2">
      <label class="text-sm text-slate-300">Name<input v-model="draft.name" required maxlength="50" class="mt-1 w-full rounded-xl border border-white/10 bg-slate-800 p-3"></label>
      <label class="text-sm text-slate-300">Character age<input :value="draft.age_years" @input="setAge" type="number" min="0" max="100000" step="1" class="mt-1 w-full rounded-xl border border-white/10 bg-slate-800 p-3"></label>
      <label class="text-sm text-slate-300 sm:col-span-2">Biography &amp; appearance<textarea v-model="draft.description" required maxlength="1000" rows="4" class="mt-1 w-full resize-y rounded-xl border border-white/10 bg-slate-800 p-3" /></label>
      <label class="text-sm text-slate-300">Goal<textarea v-model="draft.goal" maxlength="1000" rows="3" class="mt-1 w-full resize-y rounded-xl border border-white/10 bg-slate-800 p-3" /></label>
      <label class="text-sm text-slate-300">Character &amp; values<textarea v-model="draft.character" maxlength="1000" rows="3" class="mt-1 w-full resize-y rounded-xl border border-white/10 bg-slate-800 p-3" /></label>
      <label class="text-sm text-slate-300">Gender<input v-model="draft.gender" maxlength="80" class="mt-1 w-full rounded-xl border border-white/10 bg-slate-800 p-3"></label>
      <label v-for="(limit, key) in { hair: 160, eyes: 100, build: 160, features: 400 }" :key="key" class="text-sm capitalize text-slate-300">{{ key }}<input v-model="draft.appearance[key]" :maxlength="limit" class="mt-1 w-full rounded-xl border border-white/10 bg-slate-800 p-3"></label>
    </fieldset>
    <details class="rounded-xl border border-white/10 p-3 text-sm text-slate-300">
      <summary class="cursor-pointer">Traits &amp; starting stats</summary>
      <fieldset :disabled="disabled" class="mt-3 grid gap-3 sm:grid-cols-3">
        <label v-for="key in (['hp', 'stamina', 'mana'] as const)" :key="key" class="uppercase">{{ key }}<input v-model.number="draft[key]" type="number" :min="key === 'hp' ? 1 : 0" max="100000" step="1" required class="mt-1 w-full rounded-xl border border-white/10 bg-slate-800 p-2"></label>
        <label class="flex items-center gap-2"><input v-model="draft.moveable" type="checkbox" class="accent-emerald-500">Can move</label>
        <label class="flex items-center gap-2"><input v-model="draft.is_killable" type="checkbox" class="accent-emerald-500">Can be defeated</label>
      </fieldset>
      <dl class="mt-3 grid gap-2 sm:grid-cols-2"><div v-for="(value, key) in draft.personality_profile" :key="key"><dt class="capitalize text-slate-500">{{ key }}</dt><dd>{{ value || 'Follow the biography' }}</dd></div></dl>
    </details>
    <NpcDraftItems :items="draft.items" :selected="selected" :disabled="disabled" @update:items="draft.items = $event" @update:selected="emit('update:selected', $event)" />
  </section>
</template>
