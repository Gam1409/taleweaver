<script setup lang="ts">
import { watch } from 'vue'
import { ListChecks } from 'lucide-vue-next'
import ComfyModelField from './ComfyModelField.vue'
import { useComfyStarterModels, type StarterRecipe } from '@/composables/useComfyStarterModels'
import { MODEL_FIELD_FOLDERS } from '@/services/comfyWorkflowGraph'
import type { ComfyPreset } from '@/types/comfyui'

const props = defineProps<{ url: string; recipe: StarterRecipe | null; requiresFilename: boolean; disabled?: boolean }>()
const emit = defineEmits<{ prepared: [preset: ComfyPreset | null]; busy: [value: boolean] }>()
const { preset, fields, report, error, busy, check, select } = useComfyStarterModels(props, value => emit('prepared', value))
watch(busy, value => emit('busy', value), { flush: 'sync' })
</script>
<template>
  <section class="mt-4 space-y-3" aria-label="Task model check">
    <button type="button" :disabled="disabled || busy || !url.trim() || !recipe"
      class="inline-flex items-center gap-2 rounded-lg border border-cyan-600 px-4 py-2 text-sm text-cyan-200 hover:bg-cyan-500/10 disabled:opacity-40"
      @click="check">
      <ListChecks class="h-4 w-4" />{{ busy ? 'Checking model files…' : 'Check VAE / Checkpoint / CLIP' }}
    </button>
    <p v-if="!url.trim()" class="text-xs text-amber-200">Enter the ComfyUI server URL to check installed files.</p>
    <p v-if="busy" role="status" class="text-xs text-cyan-200">Reading model lists and node definitions. No image generation is started.</p>
    <p v-if="error" role="alert" class="text-sm text-rose-300">{{ error }}</p>
    <fieldset v-if="preset" :disabled="busy || disabled" class="space-y-3 rounded-lg border border-slate-700 p-4 disabled:opacity-50">
      <legend class="px-2 text-xs font-semibold text-slate-200">Model files for this task</legend>
      <p class="text-xs text-slate-400">These file selections are used by Create task preset, including its reference variant. Node compatibility is checked for the base workflow. Changing the recipe or server above resets this check.</p>
      <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <ComfyModelField v-for="field in fields" :key="`${field.id}-${field.name}`"
          :label="field.label" :model-value="field.value" :files="field.files" :folder="MODEL_FIELD_FOLDERS[field.name]"
          @update:model-value="select(field.id, field.name, $event)" />
      </div>
      <p v-if="!fields.some(field => field.name.startsWith('clip_name')) || !fields.some(field => field.name === 'vae_name')" class="text-xs text-slate-400">
        Components connected from the checkpoint are not checked as separate files. A test image is needed to confirm its embedded encoder and VAE work.
      </p>
      <div v-if="report" role="status" class="space-y-1 text-xs" :class="report.compatible ? 'text-emerald-300' : 'text-amber-200'">
        <p v-if="report.compatible">Required nodes and selected model files are available.</p>
        <p v-for="line in report.errors" :key="line">{{ line }}</p>
        <p>{{ report.message }}</p>
      </div>
      <p v-else class="text-xs text-amber-200">File selection changed. Run the check again to validate these filenames.</p>
    </fieldset>
  </section>
</template>
