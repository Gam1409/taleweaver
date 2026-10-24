<script setup lang="ts">
import { onBeforeUnmount, toRef, watch } from 'vue'
import { useNpcJournal, type NpcCard } from '@/composables/useNpcJournal'

const props = defineProps<{ sessionId: string; npcId: string }>()
const { details, loading, error, load } = useNpcJournal(toRef(props, 'sessionId'), toRef(props, 'npcId'))
const emit = defineEmits<{ loaded: [card: NpcCard] }>()
watch(details, card => { if (card) emit('loaded', card) })
const timer = setInterval(() => {
  if (details.value?.portrait_status === 'pending' || details.value?.portrait_status === 'running') void load()
}, 5000)
onBeforeUnmount(() => clearInterval(timer))
const categories: Record<string, string> = { appearance: 'Appearance', background: 'Background', relationship: 'Relationships', belongings: 'Known belongings', equipment: 'Clothing and equipment', event: 'Events' }
</script>

<template>
  <section class="mt-4 space-y-3 text-sm border-t border-slate-700 pt-4" aria-label="Character journal">
    <p v-if="error" role="alert" class="text-rose-300">{{ error }} <button class="underline" @click="load()">Retry</button></p>
    <p v-if="loading && !details" role="status" class="text-slate-400">Loading character history…</p>
    <template v-if="details">
      <p v-if="details.introduction" class="text-slate-300"><span class="text-slate-400">Introduced themselves:</span> “{{ details.introduction }}”</p>
      <p v-if="details.aliases.length" class="text-slate-400">Also known as: {{ details.aliases.join(', ') }}</p>
      <p v-if="['pending', 'running'].includes(details.portrait_status || '')" role="status" class="text-amber-200">The first portrait is being prepared. You can continue playing.</p>
      <p v-else-if="['failed', 'interrupted'].includes(details.portrait_status || '')" class="text-slate-400">The automatic portrait could not finish. Character information is saved; use Generate portrait to retry.</p>
      <details class="rounded-xl border border-slate-700 p-3" open>
        <summary class="cursor-pointer font-semibold">Learned history · {{ details.entry_count }}</summary>
        <p class="mt-2 text-xs text-slate-400">Only information your character learned in this session. Claims record what someone said, without assuming it is true. Belongings are past observations, not a live inventory. Ask, inspect or attempt a search through play to learn more.</p>
        <p v-if="!details.entries?.length" class="mt-3 text-slate-400">No further information learned yet.</p>
        <ol class="mt-3 space-y-3">
          <li v-for="entry in details.entries" :key="entry.id" class="border-l-2 border-amber-500/30 pl-3">
            <div class="text-xs text-amber-200">{{ categories[entry.category] || entry.category }} · {{ entry.source === 'claimed' ? 'Claim' : 'Observed' }}</div>
            <p class="mt-1 whitespace-pre-wrap">{{ entry.text }}</p>
            <details class="mt-1 text-xs text-slate-400"><summary class="cursor-pointer">Source passage</summary><blockquote class="mt-1 whitespace-pre-wrap">{{ entry.evidence }}</blockquote></details>
          </li>
        </ol>
        <button v-if="details.has_more" :disabled="loading" class="mt-3 underline text-amber-200 disabled:opacity-50" @click="load(true)">Load earlier entries</button>
      </details>
    </template>
  </section>
</template>
