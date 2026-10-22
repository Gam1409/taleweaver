<script setup lang="ts">
import type { OllamaRole } from '@/services/ollamaRoleSettings'
import { normalizeOllamaNumber } from '@/services/ollamaRoleSettings'

defineProps<{
  role: OllamaRole
  url?: string | null
  timeout?: number | null
  numCtx?: number | null
  globalUrl?: string
  loading: boolean
}>()
const emit = defineEmits<{
  (e: 'update:url', value: string): void
  (e: 'update:timeout', value: number | null): void
  (e: 'update:numCtx', value: number | null): void
  (e: 'refresh'): void
}>()
</script>

<template>
  <details :data-ollama-role="role" class="p-4 border border-cyan-800 rounded-xl">
    <summary class="cursor-pointer text-xs text-cyan-300 rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-cyan-400">Ollama settings (experimental)</summary>
    <fieldset class="mt-3 space-y-3">
      <legend class="sr-only">Ollama role overrides</legend>
      <label class="block text-xs text-slate-300">
        Ollama URL
        <input :value="url || ''" type="url" :placeholder="globalUrl || 'http://localhost:11434'" class="mt-1 w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white" @input="emit('update:url', ($event.target as HTMLInputElement).value)" />
      </label>
      <p class="text-xs text-slate-400">Leave blank to use {{ globalUrl || 'http://localhost:11434' }}. Each role can select its own model on the same or a separate server.</p>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <label class="block text-xs text-slate-300">
          Timeout (seconds)
          <input :value="timeout ?? ''" type="number" min="30" max="600" placeholder="Environment default" class="mt-1 w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white" @input="emit('update:timeout', normalizeOllamaNumber(($event.target as HTMLInputElement).value))" />
        </label>
        <label class="block text-xs text-slate-300">
          Context size (num_ctx)
          <input :value="numCtx ?? ''" type="number" min="512" max="1048576" placeholder="Model default" class="mt-1 w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-white" @input="emit('update:numCtx', normalizeOllamaNumber(($event.target as HTMLInputElement).value))" />
        </label>
      </div>
      <p class="text-xs text-slate-400">Blank timeout uses {{ role === 'generator' ? 'WORLDBUILDING_TIMEOUT' : 'INTELLIGENCE_TIMEOUT' }}; blank context size uses the model/server default. Timeout is per attempt; failed requests are retried up to 3 times. The bundled nginx proxy has a 300-second read timeout.</p>
      <button type="button" :disabled="loading" class="text-xs text-cyan-300 disabled:opacity-40" @click="emit('refresh')">{{ loading ? 'Loading models…' : 'Refresh role models' }}</button>
    </fieldset>
  </details>
</template>
