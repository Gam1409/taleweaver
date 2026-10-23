<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { comfyRequest } from '@/services/comfyPresetService'
import type { ComfyWorkflow } from '@/types/comfyui'

const props = defineProps<{ reference?: boolean; empty: boolean; suggestedFamily?: string; sourceWorkflow?: ComfyWorkflow | null }>()
const emit = defineEmits<{ (event: 'choose', workflow: ComfyWorkflow): void }>()
type Starter = { id: string; name: string; generate: ComfyWorkflow; reference: ComfyWorkflow }
const starters = ref<Starter[]>([])
const selected = ref(props.suggestedFamily || 'sdxl')
watch(() => props.suggestedFamily, family => { if (family) selected.value = family })
const error = ref('')
onMounted(async () => {
  try { starters.value = await comfyRequest<Starter[]>('starter-workflows') }
  catch (err) { error.value = String(err) }
})
function choose(): void {
  const item = starters.value.find(value => value.id === selected.value)
  if (!item) return
  const workflow = JSON.parse(JSON.stringify(props.reference ? item.reference : item.generate)) as ComfyWorkflow
  if (props.reference && selected.value === props.suggestedFamily && props.sourceWorkflow) {
    for (const node of Object.values(workflow.graph)) {
      const matches = Object.values(props.sourceWorkflow.graph).filter(source => source.class_type === node.class_type)
      if (matches.length !== 1) continue
      for (const field of ['ckpt_name', 'unet_name', 'clip_name', 'vae_name']) {
        if (typeof node.inputs[field] === 'string' && typeof matches[0]!.inputs[field] === 'string') node.inputs[field] = matches[0]!.inputs[field]
      }
    }
  }
  emit('choose', workflow)
}
</script>

<template>
  <details :open="empty" class="rounded-lg border border-slate-700 p-3">
    <summary class="cursor-pointer text-sm text-slate-200">Start from a template</summary>
    <div class="mt-3 space-y-3">
      <label class="block text-xs text-slate-300">Model family
        <select v-model="selected" :disabled="!starters.length" class="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 p-2">
          <option v-for="item in starters" :key="item.id" :value="item.id">{{ item.name }}</option>
        </select>
      </label>
      <p v-if="!starters.length && !error" role="status" class="text-xs text-slate-400">Loading workflow templates…</p>
      <p class="text-xs text-slate-400">Works with covers, backgrounds, character portraits, items and account avatars. TaleWeaver supplies the image size and prompt, and resolves matching model filenames from your server. Models must already be installed.</p>
      <p v-if="selected === 'anima'" class="text-xs text-slate-400">Requires the Anima diffusion model, Qwen-3 0.6B encoder and Qwen Image VAE. Prefect Anima uses this architecture; Animagine XL uses SDXL.</p>
      <p v-if="selected === 'flux1'" class="text-xs text-slate-400">For the combined FLUX.1 Dev FP8 checkpoint, including encoders and VAE. Split or Turbo models need a different workflow.</p>
      <p v-if="reference" class="text-xs text-slate-400">This is img2img with denoise 0.3. It can preserve composition, but does not guarantee face or object identity.</p>
      <p v-if="!empty" class="text-xs text-amber-300">Replaces this draft workflow. Saved preferences change only after you apply and save.</p>
      <button type="button" :disabled="!starters.length" class="rounded bg-cyan-700 px-3 py-2 text-xs text-white disabled:opacity-40" @click="choose">Use starter workflow</button>
      <p v-if="error" role="alert" class="text-xs text-rose-300">{{ error }}</p>
    </div>
  </details>
</template>
