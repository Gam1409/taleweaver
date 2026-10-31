<script setup lang="ts">
import type { LivingWorldPreferences } from '@/services/livingWorld'
const draft = defineModel<LivingWorldPreferences>({ required: true })
defineProps<{ busy: boolean; concordiaAvailable: boolean }>()
</script>

<template>
  <fieldset class="space-y-3 border-t border-white/10 pt-3" :disabled="busy">
    <legend class="text-teal-300">Private NPC decisions · Experimental</legend>
    <label class="flex gap-2"><input v-model="draft.deliberation_enabled" type="checkbox"> Allow bounded NPC decisions</label>
    <p class="text-xs text-slate-400">Uses the Utility model during idle opportunities. Requires shared inference serialization and an Ollama or OpenAI-compatible endpoint. Plans and beliefs remain private; only validated actions change the world.</p>
    <template v-if="draft.deliberation_enabled">
      <label class="block">Decision engine
        <select v-model="draft.decision_engine" class="mt-1 w-full rounded bg-slate-800 p-2">
          <option value="native">TaleWeaver</option>
          <option value="concordia" :disabled="!concordiaAvailable">Concordia 2.4 (optional)</option>
        </select>
      </label>
      <p v-if="!concordiaAvailable" class="text-xs text-slate-400">Concordia requires the optional concordia extra and Python 3.12 or 3.13 on the server.</p>
      <label class="flex gap-2"><input v-model="draft.auto_schedule" type="checkbox"> Schedule recurring NPC decisions</label>
      <div class="grid grid-cols-2 gap-3">
        <label>Game minutes between routines<input v-model.number="draft.schedule_interval_minutes" type="number" min="15" max="1440" class="mt-1 w-full rounded bg-slate-800 p-2"></label>
        <label>NPCs per routine<input v-model.number="draft.max_npcs" type="number" min="1" max="8" class="mt-1 w-full rounded bg-slate-800 p-2"></label>
        <label>Requests per batch<input v-model.number="draft.max_decisions_per_run" type="number" min="1" max="4" class="mt-1 w-full rounded bg-slate-800 p-2"></label>
        <label>Request budget for this timeline<input v-model.number="draft.max_deliberations" type="number" min="0" max="128" class="mt-1 w-full rounded bg-slate-800 p-2"></label>
        <label>Output tokens per decision<input v-model.number="draft.decision_max_tokens" type="number" min="128" max="1024" class="mt-1 w-full rounded bg-slate-800 p-2"></label>
      </div>
      <p class="text-xs text-slate-400">One batch runs when requested or once when returning if enabled above. Failed attempts also consume the budget. Stop discards a pending result; remote inference may still need administrator recovery.</p>
    </template>
  </fieldset>
</template>
