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
    <label class="flex gap-2"><input v-model="draft.live_enabled" type="checkbox"> Run automatically while playing</label>
    <label class="block">Automatic batch interval (seconds)<input v-model.number="draft.live_interval_seconds" type="number" min="20" max="600" class="ml-2 w-24 rounded bg-slate-800 p-2"></label>
    <label class="flex gap-2"><input v-model="draft.allow_concurrent_requests" type="checkbox"> Allow concurrent LLM requests</label>
    <p class="text-xs text-slate-400">Concurrent mode allows one Living World request alongside normal inference on the same endpoint (two total). Enable only if your server supports parallel requests. Changes to the same world still apply one at a time.</p>
    <label class="flex gap-2"><input v-model="draft.dialogue_choices_enabled" type="checkbox"> NPC choices in important conversations</label>
    <p class="text-xs text-slate-400">At most one extra Utility request before narration for an unambiguous NPC at a recognized English/Russian conversational branch. Shares the timeline allowance; intentions are never recorded as completed events.</p>
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
      <p class="text-xs text-slate-400">Automatic mode runs bounded batches while the session is open. Game time follows narration. Without it, batches run manually or on return. Failed attempts also consume the budget. Stop discards a pending result; remote inference may still need administrator recovery.</p>
    </template>
  </fieldset>
</template>
