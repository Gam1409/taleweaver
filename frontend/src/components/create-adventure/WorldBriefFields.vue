<script setup lang="ts">
import { BookOpen, Link2, Plus, Trash2 } from 'lucide-vue-next'

import type { WorldBrief, WorldReference } from '@/services/worldBrief'

const props = defineProps<{ modelValue: WorldBrief }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: WorldBrief): void }>()
const fields = [
  ['setting', 'Setting & canon', 'Genre, era, place, technology or magic; which canon or interpretation to use.', 2000],
  ['history', 'History before play', 'Established events and their consequences before the first scene.', 5000],
  ['opening', 'Starting situation', 'Where the story starts, who is nearby and what is already happening.', 2000],
  ['characters', 'Important people', 'Identities, values, personal motives and existing relationships.', 3000],
  ['world_rules', 'World constraints', 'Facts and limits that should stay consistent.', 2000],
  ['open_threads', 'Unresolved tensions', 'Conflicts, mysteries and possibilities to explore; leave their outcomes open.', 2000],
] as const

function update(key: keyof Omit<WorldBrief, 'references'>, value: string) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
function reference(index: number, key: keyof WorldReference, value: string) {
  emit('update:modelValue', { ...props.modelValue, references: props.modelValue.references.map((entry, i) => i === index ? { ...entry, [key]: value } : entry) })
}
function add() {
  if (props.modelValue.references.length >= 3) return
  emit('update:modelValue', { ...props.modelValue, references: [...props.modelValue.references, { url: '', excerpt: '', note: '' }] })
}
function remove(index: number) {
  emit('update:modelValue', { ...props.modelValue, references: props.modelValue.references.filter((_, i) => i !== index) })
}
</script>

<template>
  <details class="rounded-2xl border border-indigo-400/20 bg-indigo-950/10 p-4">
    <summary class="cursor-pointer text-xs font-black uppercase tracking-widest text-indigo-200"><BookOpen class="mr-2 inline h-4 w-4" /> World blueprint · optional</summary>
    <p class="my-3 text-xs leading-relaxed text-slate-400">Give the AI a world to develop, with its history and starting facts. The outcome stays open to the story and the player's decisions. These fields are used during world creation; they are not appended to every RP turn.</p>
    <div class="grid gap-4 md:grid-cols-2">
      <label v-for="[key, label, hint, limit] in fields" :key="key" class="block space-y-1 text-xs text-slate-300">
        <span class="font-bold">{{ label }}</span>
        <textarea :value="modelValue[key]" :maxlength="limit" rows="3" :placeholder="hint" class="w-full rounded-xl border border-white/10 bg-slate-950/70 p-3 text-xs text-slate-100 placeholder:text-slate-600" @input="update(key, ($event.target as HTMLTextAreaElement).value)" />
      </label>
    </div>
    <div class="mt-4 space-y-3 border-t border-white/10 pt-4">
      <h4 class="flex items-center gap-2 text-xs font-bold text-indigo-200"><Link2 class="h-4 w-4" /> Reference pages & excerpts</h4>
      <p class="text-xs text-slate-400">Up to three public HTML/text pages. The engine reads a short excerpt once and saves it for generation retries. It does not crawl an entire wiki. For a large article, choose a specific page or paste its relevant facts.</p>
      <div v-for="(source, index) in modelValue.references" :key="index" class="space-y-2 rounded-xl border border-white/10 p-3">
        <div class="flex items-center gap-2">
          <label class="min-w-0 flex-1 space-y-1 text-xs text-slate-300"><span>Source {{ index + 1 }} · public URL</span><input :value="source.url" type="url" maxlength="2048" placeholder="https://example.org/wiki/Setting" class="w-full rounded-lg border border-white/10 bg-slate-950 p-2" @input="reference(index, 'url', ($event.target as HTMLInputElement).value)" /></label>
          <button type="button" :aria-label="`Remove source ${index + 1}`" class="rounded-xl p-2 text-slate-400 transition hover:bg-rose-500/10 hover:text-rose-300" @click="remove(index)"><Trash2 class="h-4 w-4" /></button>
        </div>
        <label class="block space-y-1 text-xs text-slate-300"><span>Why this source matters</span><input :value="source.note" maxlength="300" placeholder="For example: geography and social customs; ignore its ending." class="w-full rounded-lg border border-white/10 bg-slate-950 p-2" @input="reference(index, 'note', ($event.target as HTMLInputElement).value)" /></label>
        <label class="block space-y-1 text-xs text-slate-300"><span>Pasted excerpt · optional, used instead of downloading</span><textarea :value="source.excerpt" maxlength="3000" rows="3" class="w-full rounded-lg border border-white/10 bg-slate-950 p-2" @input="reference(index, 'excerpt', ($event.target as HTMLTextAreaElement).value)" /></label>
      </div>
      <button v-if="modelValue.references.length < 3" type="button" class="flex items-center gap-2 rounded-xl border border-indigo-400/25 px-3 py-2 text-xs font-bold text-indigo-200 transition hover:bg-indigo-400/10" @click="add"><Plus class="h-4 w-4" /> Add reference</button>
      <p class="text-xs text-slate-500">Leave this blueprint empty to use your concept alone. Total brief text: up to 12,000 characters; source excerpts: up to 3,000 each. Sources are included in adventure exports.</p>
    </div>
  </details>
</template>
