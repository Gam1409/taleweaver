<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { FileCheck2, Loader2 } from 'lucide-vue-next'
import { blueprintOptions, checkBlueprint, type BlueprintCheckResult } from '@/services/blueprints'

const props = defineProps<{ text: string; options: Record<string, unknown> }>()
const result = ref<BlueprintCheckResult | null>(null)
const error = ref('')
const busy = ref(false)
let controller: AbortController | null = null
const signature = () => JSON.stringify([props.text, blueprintOptions(props.options)])

async function check() {
  controller?.abort()
  const current = new AbortController()
  const before = signature()
  controller = current
  busy.value = true
  error.value = ''
  try {
    const next = await checkBlueprint(props.text, props.options, current.signal)
    if (controller === current && before === signature()) result.value = next
  } catch (cause) {
    if (controller === current) error.value = cause instanceof Error ? cause.message : 'Blueprint check failed.'
  } finally {
    if (controller === current) busy.value = false
  }
}

watch(signature, () => {
  controller?.abort()
  controller = null
  busy.value = false
  result.value = null
  error.value = ''
})
onBeforeUnmount(() => { controller?.abort(); controller = null })
</script>

<template>
  <div class="space-y-2 text-xs">
    <div class="flex flex-wrap items-center gap-3">
      <button type="button" :disabled="busy || !text.trim()" class="flex items-center gap-2 rounded-xl border border-cyan-400/25 bg-cyan-950/30 px-3 py-2 font-bold text-cyan-200 transition hover:bg-cyan-900/40 disabled:opacity-40" @click="check">
        <Loader2 v-if="busy" class="h-4 w-4 animate-spin" /><FileCheck2 v-else class="h-4 w-4" />
        {{ busy ? 'Checking…' : 'Check blueprint' }}
      </button>
      <span class="text-slate-500">Syntax and references · no AI request</span>
    </div>
    <p v-if="error" role="alert" class="text-rose-300">{{ error }}</p>
    <div v-if="result" aria-live="polite" class="space-y-2 rounded-xl border border-white/10 bg-slate-950/50 p-3">
      <p v-if="!result.has_tags" class="text-slate-300">Free-form idea: the generator will develop the world from your description.</p>
      <p v-else-if="!result.errors.length" class="text-emerald-300">Blueprint is valid. {{ Object.entries(result.counts).map(([kind, count]) => `${kind}: ${count}`).join(' · ') }}</p>
      <p v-for="issue in result.errors" :key="`error-${issue.line}-${issue.message}`" class="text-rose-300">Line {{ issue.line }}: {{ issue.message }}</p>
      <p v-for="issue in result.warnings" :key="`warning-${issue.line}-${issue.message}`" class="text-amber-200">Line {{ issue.line }}: {{ issue.message }}</p>
    </div>
    <details class="text-slate-400">
      <summary class="cursor-pointer py-1 font-bold text-slate-300">Structured scenario syntax</summary>
      <p class="py-2">Every part is optional. Values are fixed; prefix a suggestion with ~ or use ? to leave a field open. Free text adds design notes.</p>
      <pre class="overflow-x-auto rounded-xl bg-slate-950 p-3 text-[11px] leading-relaxed text-cyan-200">[Scene: LAB] The observatory
description: ~A rain-soaked rooftop laboratory.
[NPC: MIRA] Mira
in: LAB
age: 28
gender: female
goal: Protect her research and decide whom to trust.
character: Independent, observant; speaks with dry humour.
[Item: NOTEBOOK] Mira's notebook
in: LAB
description: ?</pre>
      <p class="py-2">Character profiles and clothing accept their existing fields as JSON. Chapter, quest and script blocks follow the selected game mode and generation switches. VN keeps its open-ended story rules.</p>
    </details>
  </div>
</template>
