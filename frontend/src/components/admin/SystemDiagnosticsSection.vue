<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  systemDiagnosticsService,
  type SystemDiagnosticsSettings
} from '@/services/systemDiagnosticsService'

const settings = ref<SystemDiagnosticsSettings | null>(null)
const enabled = ref(false)
const detailedLogging = ref(false)
const stateFailureTraces = ref(false)
const loading = ref(true)
const saving = ref(false)
const feedback = ref('')
const failed = ref(false)
const changed = computed(() => settings.value !== null && (
  enabled.value !== settings.value.enabled || detailedLogging.value !== !!settings.value.detailed_logging ||
  stateFailureTraces.value !== !!settings.value.state_failure_traces
))

async function load(): Promise<void> {
  loading.value = true
  feedback.value = ''
  failed.value = false
  try {
    settings.value = await systemDiagnosticsService.getSettings()
    enabled.value = settings.value.enabled
    detailedLogging.value = !!settings.value.detailed_logging
    stateFailureTraces.value = !!settings.value.state_failure_traces
  } catch {
    failed.value = true
    feedback.value = 'Could not load system diagnostics. Retry to change this setting.'
  } finally {
    loading.value = false
  }
}

async function save(): Promise<void> {
  if (!settings.value || saving.value || !changed.value) return
  saving.value = true
  feedback.value = ''
  failed.value = false
  try {
    settings.value = await systemDiagnosticsService.saveSettings(
      enabled.value, enabled.value && detailedLogging.value, enabled.value && stateFailureTraces.value
    )
    enabled.value = settings.value.enabled
    detailedLogging.value = !!settings.value.detailed_logging
    stateFailureTraces.value = !!settings.value.state_failure_traces
    feedback.value = settings.value.write_error
      ? ''
      : enabled.value
        ? 'System diagnostics enabled. New diagnostic events will be recorded.'
        : 'System diagnostics disabled. Existing log files are kept.'
  } catch {
    failed.value = true
    feedback.value = 'The setting could not be saved. Try again.'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="space-y-8">
    <div>
      <h1 class="mb-2 text-4xl font-extrabold text-white">System Diagnostics</h1>
      <p class="text-slate-400">Record technical events to investigate errors and slow requests.</p>
    </div>
    <div class="space-y-6 rounded-3xl border border-slate-800 bg-slate-900 p-8 shadow-2xl">
      <p v-if="loading" role="status" class="text-sm text-slate-300">Loading diagnostics settings…</p>
      <div v-if="settings?.reliability" class="rounded-xl border border-slate-700 p-4 text-sm text-slate-300">
        <h2 class="font-bold text-white">Memory recall</h2>
        <p>{{ settings.reliability.scope }}. Counts are per audience projection, not unique turns.</p>
        <dl class="mt-3 grid grid-cols-2 gap-2">
          <template v-for="(value, key) in settings.reliability.recall" :key="key">
            <dt>{{ String(key).replace(/_/g, ' ') }}</dt><dd>{{ value }}</dd>
          </template>
        </dl>
        <h2 class="mt-4 font-bold text-white">Scene staging</h2>
        <p>Completed reconciliations only; skipped turns and model failures are excluded. A rejected delta clears all actor staging for that turn.</p>
        <dl class="mt-3 grid grid-cols-2 gap-2">
          <template v-for="(value, key) in settings.reliability.staging ?? {}" :key="key">
            <dt>{{ String(key).replace(/_/g, ' ') }}</dt><dd>{{ value }}</dd>
          </template>
        </dl>
        <h2 class="mt-4 font-bold text-white">Recent post-turn hooks</h2>
        <ul class="mt-2 space-y-1">
          <li v-for="(hook, index) in settings.reliability.hooks ?? []" :key="index">
            {{ hook.name }}: {{ hook.status }} ({{ hook.attempts }} attempts) {{ hook.error_type ?? '' }}
          </li>
        </ul>
        <button type="button" class="mt-3 rounded border border-slate-600 px-3 py-2" @click="load">Refresh metrics</button>
      </div>
      <form v-if="!loading && settings" class="space-y-6" @submit.prevent="save">
        <fieldset :disabled="saving" class="space-y-5 disabled:opacity-70">
          <label class="flex cursor-pointer items-center justify-between gap-4 rounded-2xl border border-white/5 bg-slate-950/40 p-5">
            <span>
              <span class="block font-bold text-white">System Debug</span>
              <span class="mt-1 block text-sm text-slate-400">Record operations, timings, statuses and errors.</span>
            </span>
            <span class="relative inline-flex shrink-0 items-center">
              <input v-model="enabled" type="checkbox" role="switch" aria-describedby="diagnostics-privacy" class="peer sr-only" />
              <span class="h-6 w-11 rounded-full bg-slate-700 after:absolute after:left-[2px] after:top-[2px] after:h-5 after:w-5 after:rounded-full after:bg-white after:transition-transform peer-checked:bg-sky-500 peer-checked:after:translate-x-5 peer-focus-visible:ring-2 peer-focus-visible:ring-sky-400 peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-slate-900" aria-hidden="true"></span>
            </span>
          </label>
          <p id="diagnostics-privacy" class="text-sm leading-relaxed text-slate-300">
            Standard diagnostics record metadata. Gameplay Debug is a separate setting.
          </p>
          <div class="grid gap-5 md:grid-cols-2">
            <label class="flex cursor-pointer items-start gap-3 rounded-2xl border border-amber-500/20 bg-slate-950/40 p-5">
              <input v-model="detailedLogging" :disabled="!enabled" type="checkbox" class="mt-1 accent-sky-500" aria-describedby="diagnostics-detail-description" />
              <span>
                <span class="block font-bold text-white">Detailed logging</span>
                <span id="diagnostics-detail-description" class="mt-1 block text-sm text-slate-300">
                  Include complete LLM prompts and responses, JSON, engine steps, validation results and state changes.
                  Logs contain private story and NPC information. Connection credentials are excluded.
                  Requires System Debug. Save to apply.
                </span>
              </span>
            </label>
            <label class="flex cursor-pointer items-start gap-3 rounded-2xl border border-amber-500/20 bg-slate-950/40 p-5">
              <input v-model="stateFailureTraces" :disabled="!enabled" type="checkbox" class="mt-1 accent-sky-500" aria-describedby="diagnostics-state-traces-description" />
              <span>
                <span class="block font-bold text-white">State rejection traces</span>
                <span id="diagnostics-state-traces-description" class="mt-1 block text-sm text-slate-300">
                  Write private state and LLM trace files only when a state check is rejected or remains unconfirmed.
                  Independent of Detailed logging. Requires System Debug. Save to apply.
                </span>
              </span>
            </label>
          </div>
          <div class="rounded-xl border border-slate-800 bg-slate-950/40 px-4 py-3 text-sm text-slate-400">
            <p>Log folder: <code class="text-sky-300">{{ settings.log_directory }}/</code> in the project directory.</p>
            <p class="mt-1">Rotated files kept: {{ settings.retention_files }}.</p>
            <p v-if="settings.max_file_bytes" class="mt-1">Maximum size per main log file: {{ Math.round(settings.max_file_bytes / 1024 / 1024) }} MB.</p>
            <p class="mt-1">Currently {{ settings.enabled ? (settings.write_error ? 'enabled, but unable to record' : 'recording') : 'disabled' }}. Save to apply changes.</p>
          </div>
          <p v-if="settings.write_error" role="alert" class="text-sm text-red-300">
            {{ settings.write_error }} Check disk space and write permissions for the log folder.
          </p>
          <button type="submit" :disabled="!changed" class="w-full rounded-xl bg-sky-600 py-4 font-bold text-white shadow-lg shadow-sky-500/20 transition-colors hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50">
            {{ saving ? 'Saving…' : 'Save Diagnostics Settings' }}
          </button>
        </fieldset>
      </form>
      <p v-if="feedback" :role="failed ? 'alert' : 'status'" :class="failed ? 'text-red-300' : 'text-emerald-300'" class="text-sm">
        {{ feedback }}
      </p>
      <button v-if="!loading && !settings" type="button" class="rounded-lg border border-slate-700 px-4 py-2 text-sm text-white hover:bg-slate-800" @click="load">
        Retry
      </button>
    </div>
  </section>
</template>
