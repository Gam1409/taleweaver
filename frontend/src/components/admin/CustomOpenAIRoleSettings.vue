<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import type { LLMRole } from '@/services/llmRoleEndpoints'

const props = defineProps<{ role: LLMRole; url?: string | null; globalUrl?: string; loading: boolean; models?: string[] }>()
const emit = defineEmits<{ 'update:url': [value: string]; refresh: [] }>()
let timer: ReturnType<typeof setTimeout> | undefined
watch([() => props.url, () => props.globalUrl], () => {
  clearTimeout(timer)
  if (!(props.url?.trim() || props.globalUrl?.trim())) return
  timer = setTimeout(() => emit('refresh'), 600)
}, { immediate: true })
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <details :data-custom-api-role="role" class="rounded-xl border border-purple-700/50 p-4">
    <summary class="cursor-pointer text-xs font-bold text-purple-300">OpenAI-Compatible API settings</summary>
    <div class="mt-3 space-y-3">
      <label class="block text-xs text-slate-300">API URL for this role
        <input :value="url || ''" type="url" :aria-label="`API URL — ${role}`" :placeholder="globalUrl || 'http://127.0.0.1:8080/v1'" class="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white" @input="emit('update:url', ($event.target as HTMLInputElement).value)">
      </label>
      <p class="text-xs text-slate-400">Leave blank to inherit the shared API URL. This role's discovery, connection test and generation use the same endpoint and the existing provider API key.</p>
      <button type="button" :disabled="loading || !(url?.trim() || globalUrl?.trim())" class="text-xs text-purple-300 underline disabled:opacity-40" @click="emit('refresh')">{{ loading ? 'Checking models…' : 'Check models at this API URL' }}</button>
      <p v-if="models !== undefined && !loading" role="status" class="text-xs text-slate-400">{{ models.length }} models returned for this URL. You can also enter a model ID manually.</p>
    </div>
  </details>
</template>
