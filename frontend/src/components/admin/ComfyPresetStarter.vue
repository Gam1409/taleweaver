<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { comfyRequest } from '@/services/comfyPresetService'
import { imagePurposes, type ImagePurpose } from '@/services/imagePurposes'
import type { ComfyPreset } from '@/types/comfyui'
type Layout = 'checkpoint' | 'diffusion'
type Source = 'embedded' | 'external'
interface Entry {
  id: string
  family: string
  family_name: string
  purpose: ImagePurpose
  name: string
  defaults: { layout: Layout; encoder_source: Source; vae_source: Source }
  layouts: Layout[]
  custom_checkpoint_required: boolean
  reference_available: boolean
  limits: { maxWidth: number; maxHeight: number; maxBytes: number }
  sources: string[]
  notes: string
}
const props = defineProps<{ purpose?: ImagePurpose; disabled?: boolean }>()
const emit = defineEmits<{ (event: 'create', preset: ComfyPreset): void }>()
const catalog = ref<Entry[]>([])
const family = ref('sdxl')
const task = ref<ImagePurpose>(props.purpose ?? 'npc')
const layout = ref<Layout>('checkpoint')
const encoder = ref<Source>('embedded')
const vae = ref<Source>('embedded')
const filename = ref('')
const error = ref('')
const busy = ref(false)
const families = computed(() => [
  ...new Map(catalog.value.map(item => [item.family, item.family_name])).entries()
])
const entry = computed(() =>
  catalog.value.find(item => item.family === family.value && item.purpose === task.value)
)
let version = 0
let disposed = false
onBeforeUnmount(() => {
  disposed = true
  version++
})
onMounted(async () => {
  try {
    const result = await comfyRequest<Entry[]>('starter-presets')
    if (!disposed) catalog.value = result
  } catch (cause) {
    if (!disposed) error.value = String(cause)
  }
})
watch(family, () => {
  const defaults = entry.value?.defaults
  if (defaults) {
    layout.value = defaults.layout
    encoder.value = defaults.encoder_source
    vae.value = defaults.vae_source
  }
  filename.value = ''
})
watch(layout, value => {
  if (value === 'diffusion') {
    encoder.value = 'external'
    vae.value = 'external'
  }
})
watch(
  [family, task, layout, encoder, vae, filename],
  () => {
    version++
    busy.value = false
    error.value = ''
  },
  { flush: 'sync' }
)
async function create(): Promise<void> {
  if (!entry.value || busy.value) return
  const current = ++version
  busy.value = true
  error.value = ''
  try {
    const result = await comfyRequest<{ preset: ComfyPreset }>('starter-presets', {
      family: family.value,
      purpose: task.value,
      layout: layout.value,
      encoder_source: encoder.value,
      vae_source: vae.value,
      checkpoint_name: filename.value.trim() || null
    })
    if (!disposed && current === version) emit('create', result.preset)
  } catch (cause) {
    if (!disposed && current === version) error.value = String(cause)
  } finally {
    if (!disposed && current === version) busy.value = false
  }
}
</script>
<template>
  <details class="mb-5 rounded-xl border border-cyan-800 bg-slate-950/50 p-4">
    <summary class="cursor-pointer font-semibold text-cyan-200">
      Create from a task template
      <span class="text-xs text-slate-400">{{
        catalog.length ? `(${catalog.length} recipes)` : ''
      }}</span>
    </summary>
    <p class="mt-3 text-xs text-slate-400">
      Creates a new editable preset. Existing presets and assignments stay unchanged until you
      apply. Model files must already be installed on your server.
    </p>
    <div class="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <label class="text-xs text-slate-300"
        >Model family<select v-model="family" class="template-input">
          <option v-for="[id, name] in families" :key="id" :value="id">{{ name }}</option>
        </select></label
      >
      <label class="text-xs text-slate-300"
        >Task<select v-model="task" class="template-input">
          <option v-for="item in imagePurposes" :key="item.id" :value="item.id">
            {{ item.label }}
          </option>
        </select></label
      >
      <label class="text-xs text-slate-300"
        >Model file layout<select v-model="layout" class="template-input">
          <option v-for="kind in entry?.layouts" :key="kind" :value="kind">
            {{
              kind === 'checkpoint'
                ? 'Checkpoint (may include encoder / VAE)'
                : 'Diffusion model only'
            }}
          </option>
        </select></label
      >
      <label class="text-xs text-slate-300"
        >Text encoders / CLIP<select
          v-model="encoder"
          :disabled="layout === 'diffusion'"
          class="template-input"
        >
          <option value="embedded">Embedded in checkpoint</option>
          <option value="external">Separate encoder files</option>
        </select></label
      >
      <label class="text-xs text-slate-300"
        >VAE<select v-model="vae" :disabled="layout === 'diffusion'" class="template-input">
          <option value="embedded">Embedded in checkpoint</option>
          <option value="external">Separate VAE file</option>
        </select></label
      >
      <label class="text-xs text-slate-300"
        >{{
          layout === 'checkpoint' && entry?.custom_checkpoint_required
            ? 'Combined checkpoint filename (required)'
            : 'Model filename override (optional)'
        }}<input
          v-model="filename"
          maxlength="240"
          placeholder="folder/model.safetensors"
          class="template-input"
      /></label>
    </div>
    <p v-if="entry" class="mt-3 text-xs text-slate-400">
      Output limit: {{ entry.limits.maxWidth }} × {{ entry.limits.maxHeight }}. Defaults use a 1024
      px long edge (512 for SD 1.5); quality-profile dimensions can override them within these
      limits.
      {{
        entry.reference_available
          ? 'Includes an optional img2img variant.'
          : 'This task starts without a reference variant.'
      }}
    </p>
    <p class="mt-2 text-xs text-amber-200/80">
      AIO is a packaging choice, not a filename guarantee. Select embedded components only when the
      checkpoint contains the correct encoder and VAE. Standard SD3.5 uses separate encoders; its
      AIO variant uses a different checkpoint.
    </p>
    <p v-if="entry" class="mt-2 text-xs text-slate-400">{{ entry.notes }}</p>
    <div class="mt-3 flex flex-wrap gap-3 text-xs">
      <a
        v-for="source in entry?.sources"
        :key="source"
        :href="source"
        target="_blank"
        rel="noopener noreferrer"
        class="text-cyan-300 underline"
        >{{ source.includes('ComfyUI') ? 'ComfyUI reference' : 'Model reference' }}</a
      >
    </div>
    <button
      type="button"
      :disabled="
        disabled ||
        busy ||
        !entry ||
        (layout === 'checkpoint' && entry.custom_checkpoint_required && !filename.trim())
      "
      class="mt-4 rounded-lg bg-cyan-700 px-4 py-2 text-sm text-white disabled:opacity-40"
      @click="create"
    >
      {{ busy ? 'Creating…' : 'Create task preset' }}
    </button>
    <p v-if="error" role="alert" class="mt-3 text-sm text-rose-300">{{ error }}</p>
  </details>
</template>
<style scoped>
.template-input {
  @apply mt-1 block w-full rounded-lg border border-slate-600 bg-slate-900 p-2.5 text-sm text-white disabled:opacity-50;
}
</style>
