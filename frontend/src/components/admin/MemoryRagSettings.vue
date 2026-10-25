<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { memoryRagPayload, memoryRagService } from '@/services/memoryRagService'
import type { MemoryRagSettings } from '@/services/memoryRagService'

const settings = reactive<MemoryRagSettings>({
  enabled: false,
  provider: 'openai',
  base_url: '',
  model: '',
  timeout_seconds: 10
})
const apiKey = ref('')
const loading = ref(true)
const loaded = ref(false)
const busy = ref<'save' | 'test' | null>(null)
const feedback = ref('')
const failed = ref(false)
const valid = computed(
  () =>
    Boolean(settings.base_url.trim() && settings.model.trim()) &&
    Number.isFinite(settings.timeout_seconds) &&
    settings.timeout_seconds >= 1 &&
    settings.timeout_seconds <= 60
)

async function load(): Promise<void> {
  loading.value = true
  feedback.value = ''
  try {
    Object.assign(settings, await memoryRagService.getSettings())
    loaded.value = true
  } catch {
    failed.value = true
    feedback.value = 'Could not load memory settings. Retry to edit them.'
  } finally {
    loading.value = false
  }
}

async function submit(action: 'save' | 'test'): Promise<void> {
  busy.value = action
  feedback.value = ''
  failed.value = false
  try {
    const payload = memoryRagPayload(settings, apiKey.value)
    if (action === 'test') {
      const result = await memoryRagService.testSettings(payload)
      failed.value = !result.ok
      feedback.value = result.ok
        ? `Embeddings connection works${result.dimensions ? ` (${result.dimensions} dimensions)` : ''}. Save to apply these settings.`
        : result.message
      return
    }
    Object.assign(settings, await memoryRagService.saveSettings(payload))
    apiKey.value = ''
    feedback.value = settings.enabled
      ? 'Memory recall enabled and settings saved.'
      : 'Memory recall disabled and settings saved.'
  } catch {
    failed.value = true
    feedback.value =
      action === 'test'
        ? 'Embeddings test failed. Check the URL, model, API key and server availability.'
        : 'Memory settings could not be saved. Check your configuration and try again.'
  } finally {
    busy.value = null
  }
}

onMounted(load)
</script>

<template>
  <details class="mt-6 rounded-2xl border border-white/10 bg-slate-900/40">
    <summary class="cursor-pointer p-6 text-lg font-bold text-white">
      Memory &amp; recall <span class="ml-2 text-xs text-slate-400">Optional</span>
    </summary>
    <div class="px-6 pb-6 space-y-5">
      <p class="text-sm text-slate-300">
        Recall relevant events from earlier turns with semantic search. An embeddings model indexes
        memories locally; TaleWeaver manages the index automatically when enabled. Summaries use
        your existing compression model during idle time.
      </p>
      <p v-if="loading" role="status" class="text-sm text-slate-300">Loading memory settings…</p>
      <form v-else-if="loaded" class="space-y-5" @submit.prevent="submit('save')">
        <fieldset :disabled="busy !== null" class="space-y-5 disabled:opacity-70">
          <label class="flex items-center gap-3 text-sm font-bold text-white"
            ><input v-model="settings.enabled" type="checkbox" class="accent-cyan-400" />Enable
            memory recall</label
          >
          <div class="grid gap-4 sm:grid-cols-2">
            <label class="space-y-2 text-sm text-slate-300"
              ><span class="block">Embeddings provider</span>
              <select v-model="settings.provider" class="memory-input">
                <option value="openai">OpenAI compatible</option>
                <option value="ollama">Ollama</option>
              </select>
            </label>
            <label class="space-y-2 text-sm text-slate-300"
              ><span class="block">Embeddings model</span>
              <input
                v-model="settings.model"
                type="text"
                :required="settings.enabled"
                :placeholder="
                  settings.provider === 'ollama' ? 'nomic-embed-text' : 'text-embedding-3-small'
                "
                class="memory-input"
              />
            </label>
            <label class="space-y-2 text-sm text-slate-300 sm:col-span-2"
              ><span class="block">Embeddings base URL</span>
              <input
                v-model="settings.base_url"
                type="url"
                :required="settings.enabled"
                :placeholder="
                  settings.provider === 'ollama'
                    ? 'http://localhost:11434'
                    : 'https://api.openai.com/v1'
                "
                class="memory-input"
              />
              <span class="block text-xs text-slate-400"
                >Use the base URL of your embeddings provider. This connection is separate from your
                conversation models.</span
              >
            </label>
            <label class="space-y-2 text-sm text-slate-300"
              ><span class="block"
                >Embeddings API key <span class="text-xs text-slate-400">(if required)</span></span
              >
              <input
                v-model="apiKey"
                type="password"
                autocomplete="new-password"
                :placeholder="
                  settings.key_configured ? 'Saved key — leave blank to keep' : 'API key'
                "
                class="memory-input"
              />
            </label>
            <label class="space-y-2 text-sm text-slate-300"
              ><span class="block">Request timeout (seconds)</span>
              <input
                v-model.number="settings.timeout_seconds"
                type="number"
                min="1"
                max="60"
                required
                class="memory-input"
              />
            </label>
          </div>
          <div class="flex flex-wrap gap-3">
            <button
              type="button"
              :disabled="!valid"
              class="rounded-lg border border-white/20 px-4 py-2 text-sm text-slate-200 hover:bg-white/10 disabled:opacity-40"
              @click="submit('test')"
            >
              {{ busy === 'test' ? 'Testing embeddings…' : 'Test embeddings' }}
            </button>
            <button
              type="submit"
              :disabled="settings.enabled && !valid"
              class="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-bold text-white hover:bg-cyan-600 disabled:opacity-40"
            >
              {{ busy === 'save' ? 'Saving…' : 'Save memory settings' }}
            </button>
          </div>
        </fieldset>
      </form>
      <p
        v-if="feedback"
        :role="failed ? 'alert' : 'status'"
        class="text-sm"
        :class="failed ? 'text-red-300' : 'text-emerald-300'"
      >
        {{ feedback }}
      </p>
      <button
        v-if="!loaded && !loading"
        type="button"
        class="text-sm text-cyan-300 underline"
        @click="load"
      >
        Retry loading settings
      </button>
    </div>
  </details>
</template>

<style scoped>
.memory-input {
  @apply block w-full rounded-lg border border-white/15 bg-slate-950 px-3 py-2 text-white outline-none focus:border-cyan-400;
}
</style>
