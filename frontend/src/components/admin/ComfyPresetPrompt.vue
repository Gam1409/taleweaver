<script setup lang="ts">
import PromptRulesEditor from './PromptRulesEditor.vue'
import type { ComfyPreset, ImagePromptRules, PromptTemplate } from '@/types/comfyui'
defineProps<{
  preset: ComfyPreset
  templates: PromptTemplate[]
  detecting: boolean
  detection: { message: string; models: string[] } | null
}>()
const emit = defineEmits<{
  (event: 'automatic', value: Event): void
  (event: 'rules', value: ImagePromptRules | null): void
  (event: 'mature', value: boolean): void
}>()
</script>
<template>
  <div class="space-y-5">
    <div class="rounded-xl border border-slate-700 bg-slate-950/40 p-4">
      <label class="flex items-start gap-3 text-sm"
        ><input
          type="checkbox"
          :checked="preset.auto_prompt_template"
          class="mt-0.5 accent-cyan-400"
          @change="emit('automatic', $event)"
        /><span>Choose template automatically from the workflow model</span></label
      >
      <div aria-live="polite" class="mt-3 space-y-1 text-xs text-slate-400">
        <p v-if="detecting">Checking model names…</p>
        <template v-else-if="detection"
          ><p>{{ detection.message }}</p>
          <p class="break-words">
            {{ detection.models.join(', ') || 'No supported base-model loader found.' }}
          </p></template
        >
        <p>
          Editing a rule disables automatic selection. Detection uses filenames, not model weights.
        </p>
      </div>
    </div>
    <PromptRulesEditor
      :model-value="preset.prompt_rules"
      :templates="templates"
      @update:model-value="emit('rules', $event)"
    />
    <div class="space-y-2 rounded-xl border border-slate-700 p-4">
      <label
        class="flex items-start gap-2 text-sm text-pink-400"
        title="Романтика и подразумеваемая близость между явно взрослыми персонажами, если это соответствует сцене."
        ><input
          :checked="preset.mature_themes"
          @change="emit('mature', ($event.target as HTMLInputElement).checked)"
          type="checkbox"
          :disabled="!preset.prompt_rules?.adapt_with_llm"
        /><span>Mature content</span></label
      >
      <p class="text-xs text-slate-400">
        Allows non-graphic romance and implied intimacy between adults when present in the scene.
        Used only with LLM prompt adaptation; manually prepared prompts are kept as entered.
      </p>
    </div>
    <p v-if="preset.reference" class="text-xs text-slate-400">
      These are the default rules for both workflows. The Reference tab can override them when its model needs different instructions.
    </p>
  </div>
</template>
