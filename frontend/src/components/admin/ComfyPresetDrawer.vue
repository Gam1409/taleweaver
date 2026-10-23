<script setup lang="ts">
import { computed, getCurrentInstance, nextTick, ref, watch } from 'vue'
import ComfyWorkflowEditor from './ComfyWorkflowEditor.vue'
import PromptRulesEditor from './PromptRulesEditor.vue'
import { comfyRequest, loadPromptTemplates } from '@/services/comfyPresetService'
import type { ComfyPreset, ImagePromptRules, PromptTemplate } from '@/types/comfyui'

const props = defineProps<{ open: boolean; preset: ComfyPreset; url: string }>()
const emit = defineEmits<{ (event: 'close'): void; (event: 'apply', preset: ComfyPreset, copy: boolean): void }>()
const dialog = ref<HTMLDialogElement>()
const titleId = `preset-drawer-${getCurrentInstance()!.uid}`
const draft = ref<ComfyPreset>(JSON.parse(JSON.stringify(props.preset)))
const tab = ref<'workflow' | 'prompt'>('workflow')
const templates = ref<PromptTemplate[]>([])
const error = ref('')
const detection = ref<{ template_id: string | null; models: string[]; message: string } | null>(null)
const detecting = ref(false)
const baseBusy = ref(false)
const referenceBusy = ref(false)
const previewing = ref(false)
const example = ref('A traveler in a red coat stands beside a stone bridge at dawn. A small brass lantern hangs from their belt.')
const preview = ref<{ positive: string; negative: string } | null>(null)
let detectionVersion = 0
const ready = computed(() => !baseBusy.value && !referenceBusy.value && Boolean(draft.value.name.trim() && draft.value.generate?.bindings.prompt && draft.value.generate.output_node && (!draft.value.reference || (draft.value.reference.bindings.prompt && draft.value.reference.bindings.image && draft.value.reference.output_node)) && (!draft.value.auto_prompt_template || detection.value?.template_id)))

watch(() => props.open, async open => {
  if (!open) { dialog.value?.close(); detectionVersion++; return }
  draft.value = JSON.parse(JSON.stringify(props.preset))
  tab.value = 'workflow'; error.value = ''; preview.value = null; detection.value = null
  await nextTick()
  dialog.value?.showModal()
  try { templates.value = await loadPromptTemplates() } catch (err) { error.value = String(err) }
  await detect()
}, { immediate: true })

watch(() => JSON.stringify([draft.value.generate?.graph, draft.value.reference?.graph]), () => { if (props.open) void detect() })
watch(() => JSON.stringify(draft.value), () => { preview.value = null })

async function detect(): Promise<void> {
  const version = ++detectionVersion
  if (!draft.value.generate) { detection.value = null; detecting.value = false; return }
  detecting.value = true
  try {
    const result = await comfyRequest<NonNullable<typeof detection.value>>('detect-template', { graph: draft.value.generate.graph, reference_graph: draft.value.reference?.graph ?? null })
    const list = await loadPromptTemplates()
    if (version !== detectionVersion) return
    detection.value = result
    if (draft.value.auto_prompt_template) {
      const item = list.find(t => t.id === result.template_id)
      draft.value.prompt_rules = item ? { ...item.rules } : null
    }
  } catch (err) { if (version === detectionVersion) error.value = String(err) }
  finally { if (version === detectionVersion) detecting.value = false }
}
function setAutomatic(event: Event): void {
  draft.value.auto_prompt_template = (event.target as HTMLInputElement).checked
  if (draft.value.auto_prompt_template) void detect()
}
function setRules(value: ImagePromptRules | null): void {
  draft.value.auto_prompt_template = false
  draft.value.prompt_rules = value
}
async function previewPrompt(): Promise<void> {
  previewing.value = true; error.value = ''; preview.value = null
  const request = JSON.stringify({ preset: draft.value, description: example.value })
  try {
    const result = await comfyRequest<{ positive: string; negative: string }>('preview-prompt', JSON.parse(request))
    if (props.open && request === JSON.stringify({ preset: draft.value, description: example.value })) preview.value = result
  }
  catch (err) { error.value = String(err) }
  finally { previewing.value = false }
}
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" :aria-labelledby="titleId" class="fixed inset-y-0 right-0 left-auto m-0 h-dvh max-h-none w-full max-w-2xl border-l border-slate-700 bg-slate-900 p-0 text-slate-200 shadow-2xl" @cancel.prevent="emit('close')">
      <div class="flex h-full flex-col">
        <header class="flex items-center justify-between gap-4 border-b border-slate-700 p-5">
          <h2 :id="titleId" class="text-lg font-semibold">Generation preset</h2>
          <button type="button" aria-label="Close preset editor" class="rounded p-2 hover:bg-slate-800" @click="emit('close')">✕</button>
        </header>
        <div class="min-h-0 flex-1 overflow-y-auto p-5 space-y-5">
          <label class="block text-sm">Preset name<input v-model="draft.name" maxlength="120" class="block mt-2 w-full rounded-lg bg-slate-950 border border-slate-700 p-3" /></label>
          <p class="text-xs text-slate-400">Changes affect every profile and story using this preset after Visual Preferences are saved. Use “Save as new” to keep the original.</p>
          <nav aria-label="Preset sections" class="flex gap-2">
            <button v-for="item in (['workflow', 'prompt'] as const)" :key="item" type="button" :aria-pressed="tab === item" :class="['rounded-lg px-4 py-2 text-sm capitalize', tab === item ? 'bg-cyan-700 text-white' : 'bg-slate-800']" @click="tab = item">{{ item }}</button>
          </nav>
          <div v-show="tab === 'workflow'" class="space-y-4">
            <ComfyWorkflowEditor v-model="draft.generate" :url="url" @busy="baseBusy = $event" />
            <details><summary class="text-sm cursor-pointer">Use a previous image (reference / img2img)</summary><ComfyWorkflowEditor v-model="draft.reference" @busy="referenceBusy = $event" reference :url="url" :suggested-family="detection?.template_id || undefined" :source-workflow="draft.generate" class="mt-3" /></details>
            <p class="text-xs text-slate-400">Required words in a mapped prompt input are replaced. Put model/LoRA trigger words in the Prompt tab's prefix or suffix. Keep LoRA strengths in the graph.</p>
          </div>
          <div v-show="tab === 'prompt'" class="space-y-5">
            <label class="flex items-start gap-2 text-sm"><input type="checkbox" :checked="draft.auto_prompt_template" @change="setAutomatic" /><span>Choose template automatically from the workflow model</span></label>
            <div aria-live="polite" class="text-xs text-slate-400 space-y-1">
              <p v-if="detecting">Checking model names…</p>
              <template v-else-if="detection"><p>{{ detection.message }}</p><p class="break-all">{{ detection.models.join(', ') || 'No supported base-model loader found.' }}</p></template>
              <p>Editing a template or rule disables automatic selection. Detection uses filenames, not model weights.</p>
            </div>
            <PromptRulesEditor :model-value="draft.prompt_rules" :templates="templates" @update:model-value="setRules" />
            <div class="space-y-2">
              <label class="flex items-start gap-2 text-sm text-pink-400" title="Романтика и подразумеваемая близость между явно взрослыми персонажами, если это соответствует сцене.">
                <input v-model="draft.mature_themes" type="checkbox" :disabled="!draft.prompt_rules?.adapt_with_llm" />
                <span>Взрослая тематика</span>
              </label>
              <p class="text-xs text-slate-400">Allows non-graphic romance and implied intimacy between adults when present in the scene. Used only with LLM prompt adaptation; manually prepared prompts are kept as entered.</p>
            </div>
            <p v-if="draft.reference" class="text-xs text-slate-400">These rules apply to both workflows. Use separate presets when your reference model needs different instructions.</p>
            <details class="rounded-xl border border-slate-700 p-4">
              <summary class="text-sm cursor-pointer">Preview the final prompt</summary>
              <label class="mt-4 block text-sm">Example description<textarea v-model="example" maxlength="12000" rows="4" class="block mt-2 w-full rounded bg-slate-950 p-3" /></label>
              <button type="button" :disabled="!ready || previewing || detecting" class="mt-3 rounded bg-cyan-700 px-4 py-2 text-sm disabled:opacity-40" @click="previewPrompt">{{ previewing ? 'Preparing…' : 'Preview prompt' }}</button>
              <p class="mt-2 text-xs text-slate-400">Uses the Small / Utility LLM when adaptation is enabled. Does not generate an image.</p>
              <div v-if="preview" class="mt-4 space-y-3 text-sm" aria-live="polite"><p class="whitespace-pre-wrap break-words">{{ preview.positive }}</p><p v-if="preview.negative" class="text-slate-400 whitespace-pre-wrap break-words">Negative: {{ preview.negative }}</p></div>
            </details>
          </div>
          <p v-if="error" role="alert" class="text-sm text-rose-300">{{ error }}</p>
          <p v-if="draft.generate && draft.auto_prompt_template && !detecting && !detection?.template_id" class="text-sm text-amber-300">Open Prompt and choose a template manually before applying.</p>
        </div>
        <footer class="flex flex-wrap justify-end gap-3 border-t border-slate-700 p-5">
          <button type="button" class="px-3 py-2 text-sm" @click="emit('close')">Discard</button>
          <button type="button" :disabled="!ready || detecting" class="rounded-lg border border-slate-600 px-3 py-2 text-sm disabled:opacity-40" @click="emit('apply', draft, true)">Save as new</button>
          <button type="button" :disabled="!ready || detecting" class="rounded-lg bg-cyan-700 px-4 py-2 text-sm disabled:opacity-40" @click="emit('apply', draft, false)">Apply to form</button>
        </footer>
      </div>
    </dialog>
  </Teleport>
</template>

<style scoped>
dialog::backdrop { background: rgb(2 6 23 / 75%); }
</style>
