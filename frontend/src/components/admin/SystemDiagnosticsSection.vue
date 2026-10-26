<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  systemDiagnosticsService,
  type SystemDiagnosticsSettings
} from '@/services/systemDiagnosticsService'

const settings = ref<SystemDiagnosticsSettings | null>(null)
const enabled = ref(false)
const loading = ref(true)
const saving = ref(false)
const feedback = ref('')
const failed = ref(false)
const changed = computed(() => settings.value !== null && enabled.value !== settings.value.enabled)

async function load(): Promise<void> {
  loading.value = true
  feedback.value = ''
  failed.value = false
  try {
    settings.value = await systemDiagnosticsService.getSettings()
    enabled.value = settings.value.enabled
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
    settings.value = await systemDiagnosticsService.saveSettings(enabled.value)
    enabled.value = settings.value.enabled
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
      <form v-else-if="settings" class="space-y-6" @submit.prevent="save">
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
            This diagnostic log excludes player messages, prompts, model responses, API keys and
            passwords. It does not enable gameplay debug or prompt logging.
          </p>
          <div class="rounded-xl border border-slate-800 bg-slate-950/40 px-4 py-3 text-sm text-slate-400">
            <p>Log folder: <code class="text-sky-300">{{ settings.log_directory }}/</code> in the project directory.</p>
            <p class="mt-1">Rotated files kept: {{ settings.retention_files }}.</p>
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
