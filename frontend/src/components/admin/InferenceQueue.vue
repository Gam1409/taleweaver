<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { apiFetch } from '@/services/http'

type Reservation = { endpoint_id: string; token: string; started: number; status: string }
const enabled = ref(false)
const reservations = ref<Reservation[]>([])
const error = ref('')
const busy = ref(false)
const confirmed = ref<Record<string, boolean>>({})

async function load(): Promise<void> {
  try {
    const response = await apiFetch('/inference-queue')
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Could not load inference queue.')
    enabled.value = data.enabled
    reservations.value = data.reservations
    confirmed.value = {}
    error.value = ''
  } catch (cause) { error.value = cause instanceof Error ? cause.message : 'Could not load inference queue.' }
}

async function acknowledge(row: Reservation): Promise<void> {
  if (!confirmed.value[row.token] || busy.value) return
  busy.value = true
  try {
    const response = await apiFetch('/inference-queue/acknowledge-stopped', {
      method: 'POST', includeJson: true,
      body: JSON.stringify({ endpoint_id: row.endpoint_id, token: row.token, confirmation: 'REMOTE_GENERATION_STOPPED' }),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Could not clear reservation.')
    await load()
  } catch (cause) { error.value = cause instanceof Error ? cause.message : 'Could not clear reservation.' }
  finally { busy.value = false }
}

onMounted(load)
</script>

<template>
  <section class="rounded-xl border border-teal-500/30 p-4 space-y-3">
    <h3 class="font-bold text-teal-300">Inference queue · Experimental</h3>
    <p class="text-sm text-slate-400">{{ enabled ? 'Enabled' : 'Disabled' }}. Enable with INFERENCE_SERIALIZATION_ENABLED=true in backend configuration and restart. Applies to Ollama, OpenAI-compatible servers and configured embeddings.</p>
    <p class="text-sm text-slate-400">A timeout does not prove the remote model stopped. Check or restart that inference server before clearing an uncertain request. This button does not cancel remote generation.</p>
    <p v-if="!reservations.length" class="text-sm">No outstanding reservations.</p>
    <div v-for="row in reservations" :key="row.token" class="rounded border border-white/10 p-3 space-y-2">
      <p class="text-sm">{{ row.status }} · {{ new Date(row.started * 1000).toLocaleString() }}</p>
      <p class="text-xs break-all text-slate-400">Endpoint fingerprint: {{ row.endpoint_id }}</p>
      <template v-if="row.status === 'UNCERTAIN'">
        <label class="flex gap-2 text-sm"><input v-model="confirmed[row.token]" type="checkbox"> I verified that remote generation has stopped.</label>
        <button type="button" class="rounded bg-teal-800 px-3 py-2 text-sm disabled:opacity-40" :disabled="busy || !confirmed[row.token]" @click="acknowledge(row)">Clear stopped request</button>
      </template>
    </div>
    <p v-if="error" role="alert" class="text-red-300 text-sm">{{ error }}</p>
    <button type="button" :disabled="busy" class="text-sm underline" @click="load">Refresh queue</button>
  </section>
</template>
