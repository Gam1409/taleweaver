<script setup lang="ts">
import { computed, getCurrentInstance, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import {
  BookOpen,
  Workflow,
  Image,
  TextCursorInput,
  FlaskConical,
  X,
  Plus,
  Copy,
  SlidersHorizontal
} from 'lucide-vue-next'
import ComfyWorkflowSlot from './ComfyWorkflowSlot.vue'
import PromptRulesEditor from './PromptRulesEditor.vue'
import ComfyPresetLibrary from './ComfyPresetLibrary.vue'
import ComfyPresetPrompt from './ComfyPresetPrompt.vue'
import ComfyPresetTest from './ComfyPresetTest.vue'
import { imagePurposes, type ImagePurpose } from '@/services/imagePurposes'
import { useComfyPresetWorkspace } from '@/composables/useComfyPresetWorkspace'
import type { ComfyOptions, ComfyTestOptions } from '@/types/comfyui'

const props = defineProps<{
  open: boolean
  modelValue: ComfyOptions
  profile: 'simple' | 'advanced'
  purpose?: ImagePurpose
  testResult?: { status: string; message: string; image_url?: string }
}>()
const emit = defineEmits<{
  (event: 'close'): void
  (event: 'apply', options: ComfyOptions): void
  (event: 'test', options: ComfyTestOptions): void
}>()
const {
  workspace,
  draft,
  templates,
  error,
  detection,
  detecting,
  baseBusy,
  referenceBusy,
  previewing,
  example,
  preview,
  invalid,
  ready,
  add,
  result,
  testOptions,
  setAutomatic,
  setRules,
  previewPrompt,
  removeSelectedPreset,
  connectionProblem
} = useComfyPresetWorkspace(props)
const dialog = ref<HTMLDialogElement>()
const id = `preset-settings-${getCurrentInstance()!.uid}`
const tabs = [
  { id: 'presets', label: 'Presets', icon: BookOpen, hint: 'Choose, name or duplicate a preset.' },
  {
    id: 'workflow',
    label: 'Workflow',
    icon: Workflow,
    hint: 'Models, sampling and generation parameters.'
  },
  {
    id: 'reference',
    label: 'Reference',
    icon: Image,
    hint: 'Configure an optional reference-image workflow and its prompt rules.'
  },
  {
    id: 'prompt',
    label: 'Prompt',
    icon: TextCursorInput,
    hint: 'Choose the output format and model instructions.'
  },
  {
    id: 'test',
    label: 'Test',
    icon: FlaskConical,
    hint: 'Preview the prompt or generate a test image.'
  }
] as const
const tab = ref<string>('presets')
const active = computed(() => tabs.find(item => item.id === tab.value)!)
const testSignature = ref('')
const signature = computed(() =>
  JSON.stringify([
    workspace.value.selectedId,
    draft.value,
    workspace.value.url,
    workspace.value.timeout,
    example.value,
    preview.value?.body,
  ])
)
const showTestResult = computed(() => testSignature.value === signature.value && props.testResult)
let restoreFocus: HTMLElement | null = null

watch(
  () => props.open,
  async open => {
    if (!open) {
      dialog.value?.close()
      restoreFocus?.focus()
      return
    }
    restoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    tab.value = 'presets'
    testSignature.value = ''
    await nextTick()
    if (props.open && !dialog.value?.open) dialog.value?.showModal()
  },
  { immediate: true }
)
watch(
  () => workspace.value.selectedId,
  () => {
    baseBusy.value = false
    referenceBusy.value = false
  }
)
onBeforeUnmount(() => dialog.value?.close())
function navigate(event: KeyboardEvent): void {
  const index = tabs.findIndex(item => item.id === tab.value)
  const target = {
    ArrowRight: (index + 1) % tabs.length,
    ArrowLeft: (index + tabs.length - 1) % tabs.length,
    Home: 0,
    End: tabs.length - 1
  }[event.key]
  if (target === undefined) return
  event.preventDefault()
  tab.value = tabs[target]!.id
  void nextTick(() => document.getElementById(`${id}-tab-${tab.value}`)?.focus())
}
function testImage(): void {
  if (!ready.value || !example.value.trim() || previewing.value || props.testResult?.status === 'loading') return
  testSignature.value = signature.value
  emit('test', testOptions())
}
function apply(): void {
  if (!ready.value) return
  try { emit('apply', result()) } catch (cause) { error.value = String(cause) }
}
function create(copy = false): void {
  add(copy)
  tab.value = 'presets'
}
</script>

<template>
  <Teleport to="body">
    <dialog
      ref="dialog"
      :aria-labelledby="`${id}-title`"
      class="preset-modal fixed inset-0 m-auto h-dvh max-h-dvh w-full max-w-none overflow-hidden border border-slate-700 bg-slate-900 p-0 text-slate-200 shadow-2xl sm:h-[min(90dvh,960px)] sm:max-h-[90dvh] sm:w-[calc(100vw-3rem)] sm:max-w-7xl sm:rounded-2xl"
      @cancel.prevent="emit('close')"
    >
      <div class="flex h-full min-h-0 flex-col">
        <header
          class="shrink-0 border-b border-slate-700/70 bg-slate-900 px-4 py-4 sm:px-7 sm:py-5"
        >
          <div class="flex items-start justify-between gap-4">
            <div class="flex items-center gap-3">
              <span class="rounded-xl border border-cyan-400/20 bg-cyan-400/10 p-2.5 text-cyan-300"
                ><SlidersHorizontal :size="22"
              /></span>
              <div>
                <h2 :id="`${id}-title`" class="text-lg font-semibold text-white sm:text-xl">
                  Image generation settings
                </h2>
                <p class="mt-1 text-xs text-slate-400">
                  ComfyUI · {{ purpose ? imagePurposes.find(item => item.id === purpose)?.label : profile === 'simple' ? 'Default simple profile' : 'Default advanced profile' }}
                </p>
              </div>
            </div>
            <button
              type="button"
              aria-label="Close preset settings"
              class="rounded-lg p-2 text-slate-400 hover:bg-slate-800 hover:text-white focus-visible:outline focus-visible:outline-cyan-400"
              @click="emit('close')"
            >
              <X :size="20" />
            </button>
          </div>
          <div class="mt-4 flex flex-wrap items-end gap-2 sm:gap-3">
            <label class="min-w-0 flex-1 text-xs text-slate-400"
              >Selected preset<select
                v-model="workspace.selectedId"
                class="mt-1.5 block w-full rounded-lg border border-slate-600 bg-slate-950 px-3 py-2.5 text-sm text-white focus:border-cyan-400"
              >
                <option v-for="(preset, key) in workspace.presets" :key="key" :value="key">
                  {{ preset.name || 'Unnamed preset' }}
                </option>
              </select></label
            >
            <button
              type="button"
              class="action-button"
              :disabled="Object.keys(workspace.presets).length >= 32"
              @click="create()"
            >
              <Plus :size="16" />New
            </button>
            <button
              type="button"
              class="action-button"
              :disabled="Object.keys(workspace.presets).length >= 32"
              @click="create(true)"
            >
              <Copy :size="15" />Duplicate
            </button>
          </div>
        </header>
        <div
          role="tablist"
          aria-label="Preset settings sections"
          class="flex shrink-0 gap-1 overflow-x-auto border-b border-slate-700/70 bg-slate-950/40 px-3 pt-2 sm:px-6"
          @keydown="navigate"
        >
          <button
            v-for="item in tabs"
            :id="`${id}-tab-${item.id}`"
            :key="item.id"
            type="button"
            role="tab"
            :aria-selected="tab === item.id"
            :aria-controls="`${id}-panel-${item.id}`"
            :tabindex="tab === item.id ? 0 : -1"
            class="flex shrink-0 items-center gap-2 border-b-2 px-3 py-3 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-cyan-400 sm:px-5"
            :class="
              tab === item.id
                ? 'border-cyan-400 bg-cyan-400/5 text-cyan-300'
                : 'border-transparent text-slate-400 hover:bg-slate-800 hover:text-slate-200'
            "
            @click="tab = item.id"
          >
            <component :is="item.icon" :size="16" />{{ item.label }}
          </button>
        </div>
        <main class="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-5 sm:px-7 sm:py-6">
          <div class="mb-5">
            <h3 class="font-semibold text-white">{{ active.label }}</h3>
            <p class="mt-1 text-sm text-slate-400">{{ active.hint }}</p>
          </div>
          <section
            v-show="tab === 'presets'"
            :id="`${id}-panel-presets`"
            role="tabpanel"
            :aria-labelledby="`${id}-tab-presets`"
            class="space-y-5"
          >
            <ComfyPresetLibrary
              :workspace="workspace"
              :purpose="purpose"
              @select="workspace.selectedId = $event"
              @rename="draft.name = $event"
              @remove-preset="removeSelectedPreset"
              @configure="tab = 'workflow'"
            />
          </section>
          <section
            v-if="tab === 'workflow'"
            :id="`${id}-panel-workflow`"
            role="tabpanel"
            :aria-labelledby="`${id}-tab-workflow`"
            class="space-y-4"
          >
            <ComfyWorkflowSlot
              :key="workspace.selectedId"
              v-model="draft.generate"
              :url="workspace.url"
              :library="workspace.workflows"
              @forget="delete workspace.workflows[$event]"
            />
            <p class="text-xs text-slate-400">
              Put model trigger words in the Prompt tab's prefix or suffix. Keep LoRA strengths in
              the workflow.
            </p>
          </section>
          <section
            v-if="tab === 'reference'"
            :id="`${id}-panel-reference`"
            role="tabpanel"
            :aria-labelledby="`${id}-tab-reference`"
          >
            <ComfyWorkflowSlot
              :key="workspace.selectedId"
              v-model="draft.reference"
              :url="workspace.url"
              :library="workspace.workflows"
              @forget="delete workspace.workflows[$event]"
              reference
              :suggested-family="detection?.template_id || undefined"
              :source-workflow="draft.generate"
            />
            <div v-if="draft.reference" class="mt-5 space-y-4 rounded-xl border border-slate-700 p-4">
              <label class="flex gap-2 text-sm"><input type="checkbox" :checked="Boolean(draft.reference_prompt_rules)" @change="draft.reference_prompt_rules = ($event.target as HTMLInputElement).checked ? { ...(draft.prompt_rules ?? templates[0]!.rules) } : null" :disabled="!draft.prompt_rules && !templates.length" />Use different prompt rules for the reference workflow</label>
              <p class="text-xs text-slate-400">By default both variants use the Prompt tab. Override only when the reference model requires a different format or instructions. The preset's content settings still apply.</p>
              <PromptRulesEditor v-if="draft.reference_prompt_rules" :model-value="draft.reference_prompt_rules" :templates="templates" @update:model-value="draft.reference_prompt_rules = $event" />
            </div>
          </section>
          <section
            v-show="tab === 'prompt'"
            :id="`${id}-panel-prompt`"
            role="tabpanel"
            :aria-labelledby="`${id}-tab-prompt`"
            class="space-y-5"
          >
            <ComfyPresetPrompt
              :preset="draft"
              :templates="templates"
              :detection="detection"
              :detecting="detecting"
              @automatic="setAutomatic"
              @rules="setRules"
              @mature="draft.mature_themes = $event"
            />
          </section>
          <section
            v-show="tab === 'test'"
            :id="`${id}-panel-test`"
            role="tabpanel"
            :aria-labelledby="`${id}-tab-test`"
          >
            <ComfyPresetTest
              v-model:example="example"
              :ready="ready && Boolean(example.trim())"
              :previewing="previewing"
              :preview="preview"
              :loading="testResult?.status === 'loading'"
              :test-result="showTestResult || undefined"
              @preview="previewPrompt"
              @generate="testImage"
            />
          </section>
          <p
            v-if="error"
            role="alert"
            class="mt-4 rounded-lg border border-rose-500/30 bg-rose-500/5 p-3 text-sm text-rose-300"
          >
            {{ error }}
          </p>
        </main>
        <footer
          class="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-slate-700 bg-slate-900 px-4 py-4 sm:px-7"
        >
          <div class="min-w-0 flex-1">
            <p v-if="connectionProblem" role="status" class="text-xs text-amber-300">
              {{ connectionProblem }}
            </p>
            <p v-else-if="invalid.length" role="status" class="text-xs text-amber-300">
              {{ invalid[0]!.name }}: {{ invalid[0]!.reason }}
            </p>
            <p class="mt-1 text-xs text-slate-400">
              Apply here, then Save Visual Preferences to keep your changes.
            </p>
          </div>
          <div class="flex gap-2">
            <button
              type="button"
              class="rounded-lg px-3 py-2.5 text-sm text-slate-300 hover:bg-slate-800"
              @click="emit('close')"
            >
              Discard changes</button
            ><button type="button" :disabled="!ready" class="primary-button" @click="apply">
              Apply to form
            </button>
          </div>
        </footer>
      </div>
    </dialog>
  </Teleport>
</template>

<style scoped>
.preset-modal::backdrop {
  background: rgb(2 6 23 / 78%);
  backdrop-filter: blur(5px);
}
.action-button {
  @apply flex items-center justify-center gap-2 rounded-lg border border-slate-600 px-3 py-2.5 text-sm text-slate-200 hover:bg-slate-800 disabled:opacity-40 focus-visible:outline focus-visible:outline-cyan-400;
}
.primary-button {
  @apply rounded-lg bg-cyan-700 px-4 py-2.5 text-sm font-medium text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline focus-visible:outline-cyan-400;
}
</style>
