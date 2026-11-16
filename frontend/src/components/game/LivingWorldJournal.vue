<script setup lang="ts">
import { ref } from 'vue'
import { livingWorldRequest } from '@/services/livingWorld'
const props = defineProps<{ sessionId: string }>()
interface Journal {
  private_notes: Record<string, { goal: string; belief: string; observations: string[] }>
  events: { event_id: string; actor: string; status: string; due: number; result: string }[]
}
const journal = ref<Journal | null>(null)
const error = ref('')
async function load(): Promise<void> {
  try { journal.value = await livingWorldRequest<Journal>(props.sessionId, '/events'); error.value = '' }
  catch (cause) { error.value = cause instanceof Error ? cause.message : 'Could not load private journal.' }
}
</script>

<template>
  <details class="border-t border-white/10 pt-3" @toggle="($event.target as HTMLDetailsElement).open && load()">
    <summary class="cursor-pointer text-sm">Private simulation journal (administrator)</summary>
    <p class="my-2 text-xs text-amber-300">Spoilers. Goals are intentions; beliefs may be wrong. Spoken claims are not verified facts.</p>
    <button type="button" class="text-xs underline" @click="load">Refresh journal</button>
    <p v-if="error" role="alert" class="text-red-300">{{ error }}</p>
    <div v-if="journal" class="max-h-80 space-y-3 overflow-auto text-xs">
      <section v-for="(notes, actor) in journal.private_notes" :key="actor" class="mt-3 rounded bg-slate-900 p-3">
        <strong>{{ actor }}</strong><p>Goal: {{ notes.goal }}</p><p>Belief (unverified): {{ notes.belief }}</p>
        <p v-for="(observation, index) in notes.observations" :key="index">Observed: {{ observation }}</p>
      </section>
      <p v-for="event in journal.events.slice(-30)" :key="event.event_id">{{ event.due }} · {{ event.actor }} · {{ event.status }} · {{ event.result }}</p>
    </div>
  </details>
</template>
