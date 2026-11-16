<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { comfyRequest } from '@/services/comfyPresetService'
import { addStandardPresets, type StandardPresetBundle } from '@/services/comfyStandardPresets'
import type { PresetWorkspace } from '@/services/comfyPresetDraft'
import type { ImagePurpose } from '@/services/imagePurposes'

const props = defineProps<{ workspace: PresetWorkspace; purpose?: ImagePurpose }>()
const busy = ref(false)
const message = ref('')
let disposed = false
onBeforeUnmount(() => { disposed = true })
async function add(): Promise<void> {
  if (busy.value) return
  const workspace = props.workspace
  busy.value = true
  message.value = ''
  try {
    const bundle = await comfyRequest<StandardPresetBundle>('standard-presets')
    if (disposed || props.workspace !== workspace) return
    const count = addStandardPresets(workspace, bundle, props.purpose)
    message.value = count ? `${count} standard presets added to this draft. Apply to save.` : 'All standard presets are already in this library.'
  } catch (cause) {
    if (!disposed && props.workspace === workspace) message.value = String(cause)
  } finally {
    if (!disposed) busy.value = false
  }
}
</script>

<template>
  <div class="mb-4 space-y-2 rounded-xl border border-slate-700 bg-slate-950/40 p-4">
    <button type="button" :disabled="busy" class="rounded-lg border border-cyan-700 px-3 py-2 text-sm text-cyan-200 disabled:opacity-40" @click="add">
      {{ busy ? 'Adding presets…' : 'Add standard presets · Anima + Illustrious' }}
    </button>
    <p class="text-xs text-slate-400">
      Eight tasks per family, with workflows and prompt rules already selected. Existing presets
      are kept; review the selected preset before applying. Install the required model files or adjust their
      filenames in the workflow. Reference variants use img2img.
    </p>
    <p v-if="message" role="status" class="text-sm text-cyan-200">{{ message }}</p>
  </div>
</template>
