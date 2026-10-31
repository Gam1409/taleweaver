<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { livingWorldRequest, type LivingWorldPreferences, type LivingWorldStatus } from '@/services/livingWorld'

const props = defineProps<{ sessionId: string }>()
const status = ref<LivingWorldStatus | null>(null)
const draft = ref<LivingWorldPreferences | null>(null)
const error = ref('')
const busy = ref(false)
const dirty = computed(() => JSON.stringify(draft.value) !== JSON.stringify(status.value?.settings))

async function load(): Promise<void> {
  try {
    const result = await livingWorldRequest<LivingWorldStatus>(props.sessionId)
    status.value = result
    draft.value = { ...result.settings }
    error.value = ''
  } catch (cause) { error.value = cause instanceof Error ? cause.message : 'Could not load Living World.' }
}

async function save(): Promise<boolean> {
  if (busy.value || !status.value || !draft.value) return false
  if (!dirty.value) return true
  busy.value = true
  try {
    status.value = await livingWorldRequest<LivingWorldStatus>(props.sessionId, '', 'PATCH', {
      settings: draft.value, expected_revision: status.value.revision,
    })
    draft.value = { ...status.value.settings }
    error.value = ''
    window.dispatchEvent(new CustomEvent('living-world-settings-changed'))
    return true
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Could not save Living World.'
    return false
  } finally { busy.value = false }
}

async function resume(): Promise<void> {
  if (!status.value || busy.value || !await save()) return
  busy.value = true
  error.value = ''
  try {
    status.value = await livingWorldRequest<LivingWorldStatus>(props.sessionId, '/resume', 'POST', { expected_revision: status.value.revision })
  } catch (cause) { error.value = cause instanceof Error ? cause.message : 'Could not continue simulation.' }
  finally { busy.value = false }
}

async function stop(): Promise<void> {
  try { await livingWorldRequest(props.sessionId, '/stop', 'POST') }
  catch (cause) { error.value = cause instanceof Error ? cause.message : 'Could not stop simulation.' }
}

onMounted(load)
defineExpose({ save })
</script>

<template>
  <section class="space-y-3 rounded-xl border border-teal-500/30 p-4" aria-labelledby="living-world-title">
    <h4 id="living-world-title" class="font-bold text-teal-300">Living World · Experimental</h4>
    <p class="text-xs text-slate-400">Local persistence and bounded rules simulation. Autonomous LLM decisions and Concordia are not enabled in this preview.</p>
    <template v-if="draft && status">
      <label class="flex items-center gap-2 text-sm"><input v-model="draft.living_world_enabled" type="checkbox" :disabled="busy"> Enable Living World for this session</label>
      <div v-if="draft.living_world_enabled" class="space-y-3 text-sm">
        <label class="block">Offline time
          <select v-model="draft.mode" :disabled="busy" class="mt-1 w-full rounded bg-slate-800 p-2">
            <option value="PAUSE">Pause while away</option>
            <option value="CATCH_UP">Catch up when returning</option>
          </select>
        </label>
        <p class="text-xs text-slate-400">Pause preserves the game clock. Catch-up counts offline time once and retains any unfinished remainder.</p>
        <div class="grid grid-cols-2 gap-3">
          <label>Game hours per real hour<input v-model.number="draft.offline_time_scale" type="number" min="0" max="24" step="0.1" :disabled="busy" class="mt-1 w-full rounded bg-slate-800 p-2"></label>
          <label>Game hours per run<input v-model.number="draft.max_catchup_game_hours" type="number" min="0" max="72" step="0.5" :disabled="busy" class="mt-1 w-full rounded bg-slate-800 p-2"></label>
          <label>Events per run<input v-model.number="draft.max_events" type="number" min="0" max="128" :disabled="busy" class="mt-1 w-full rounded bg-slate-800 p-2"></label>
          <label>Seconds per run<input v-model.number="draft.max_wall_seconds" type="number" min="0" max="10" step="0.5" :disabled="busy" class="mt-1 w-full rounded bg-slate-800 p-2"></label>
        </div>
        <label class="flex items-center gap-2"><input v-model="draft.auto_catchup_on_resume" type="checkbox" :disabled="busy"> Run one bounded batch when returning</label>
        <p role="status">{{ busy ? 'Working…' : status.status }} · Game minute {{ status.cursor }} / {{ status.target }}</p>
        <p class="text-xs text-slate-400">{{ status.pending_events }} pending events · {{ status.last_run_events }} processed last run · No LLM calls</p>
        <p v-if="status.status === 'WAITING_FOR_LLM'" class="text-xs text-amber-300">A decision requires an unavailable reasoning adapter. No result was invented and dependent time has not advanced.</p>
        <div class="flex flex-wrap gap-2">
          <button type="button" :disabled="busy" class="rounded bg-teal-800 px-3 py-2 disabled:opacity-40" @click="resume">Continue catch-up</button>
          <button type="button" class="rounded border border-white/20 px-3 py-2" @click="stop">Stop after current event</button>
        </div>
        <p v-for="(line, index) in status.recap" :key="index" class="text-sm">{{ line }}</p>
      </div>
      <button type="button" :disabled="busy || !dirty" class="rounded border border-teal-500/50 px-3 py-2 text-sm disabled:opacity-40" @click="save">Save Living World settings</button>
    </template>
    <p v-if="error" role="alert" class="text-sm text-red-300">{{ error }}</p>
    <button type="button" :disabled="busy" class="text-xs underline" @click="load">Refresh status</button>
  </section>
</template>
