<script setup lang="ts">
import { computed } from 'vue'
import type { PlayerClothing } from '@/types'

const props = defineProps<{ clothing?: PlayerClothing | null }>()
const appearance = computed(() => {
  const value = props.clothing?.appearance
  if (!value) return []
  const age = typeof value.age_years === 'number' && Number.isFinite(value.age_years) && value.age_years >= 0
    ? `${value.age_years} years` : ''
  return [
    { label: 'Age', text: age },
    { label: 'Hair', text: value.hair },
    { label: 'Eyes', text: value.eyes },
    { label: 'Build', text: value.build },
    { label: 'Distinguishing features', text: value.features },
  ].filter(entry => typeof entry.text === 'string' && entry.text.trim())
})
const groups = computed(() => {
  const worn = [...(props.clothing?.worn || [])].sort((first, second) => second.layer - first.layer)
  return [
    { id: 'outfit', label: props.clothing?.detail_limited ? 'General outfit' : 'Worn clothing', items: worn.filter(item => !item.underwear) },
    { id: 'underlayers', label: 'Underlayers', items: worn.filter(item => item.underwear) },
  ].filter(group => group.id === 'outfit' || group.items.length)
})
</script>

<template>
  <section aria-label="Your appearance and clothing" class="min-w-0 space-y-5 text-sm">
    <div>
      <h4 class="font-semibold text-slate-100">Your appearance</h4>
      <dl v-if="appearance.length" class="mt-3 grid grid-cols-2 gap-3">
        <div v-for="entry in appearance" :key="entry.label" class="min-w-0 rounded-xl border border-slate-700/60 bg-slate-950/30 p-3" :class="entry.label === 'Distinguishing features' ? 'col-span-2' : ''">
          <dt class="text-xs text-slate-400">{{ entry.label }}</dt>
          <dd class="mt-1 whitespace-pre-wrap break-words text-slate-200">{{ entry.text }}</dd>
        </div>
      </dl>
      <p v-else class="mt-2 text-slate-400">Appearance details will appear as the story establishes them.</p>
    </div>
    <p class="text-xs leading-relaxed text-slate-400">Your current outfit, including recorded layers covered by other clothing. Change it through actions in the story.</p>
    <component :is="group.items.length > 6 ? 'details' : 'section'" v-for="group in groups" :key="group.id" class="rounded-xl border border-slate-700/60 bg-slate-950/30 p-4">
      <summary v-if="group.items.length > 6" class="cursor-pointer font-semibold text-slate-100">{{ group.label }} · {{ group.items.length }}</summary>
      <h4 v-else class="font-semibold text-slate-100">{{ group.label }}</h4>
      <ul v-if="group.items.length" class="mt-3 space-y-3">
        <li v-for="item in group.items" :key="item.item_id" class="min-w-0 border-l-2 border-slate-600 pl-3">
          <div class="flex flex-wrap items-baseline justify-between gap-2">
            <span class="font-medium text-slate-200 break-words">{{ item.name }}</span>
            <span class="text-xs text-slate-400">{{ item.visible ? 'Visible' : 'Covered' }}</span>
          </div>
          <p v-if="item.description" class="mt-1 whitespace-pre-wrap break-words leading-relaxed text-slate-400">{{ item.description }}</p>
        </li>
      </ul>
      <p v-else class="mt-2 text-slate-400">No worn clothing details recorded yet.</p>
    </component>
  </section>
</template>
