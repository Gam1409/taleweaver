<script setup lang="ts">
import { computed, ref } from 'vue'
import ComfyDialog from './ComfyDialog.vue'
import ComfyPresetModal from './ComfyPresetModal.vue'
import ComfyPresetBrowser from './ComfyPresetBrowser.vue'
import { imagePurposes, type PresetAssignment } from '@/services/imagePurposes'
import { clonePresetData } from '@/services/comfyPresetDraft'
import type { ComfyOptions } from '@/types/comfyui'
const props = defineProps<{
  modelValue: ComfyOptions
  settings: Record<string, unknown>
  testResults: Record<string, { status: string; message: string; image_url?: string }>
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: ComfyOptions): void
  (e: 'test', value: { options: ComfyOptions; profile: 'simple' | 'advanced' }): void
}>()
const open = ref(false)
const editing = ref(false)
const draft = ref<ComfyOptions>(clonePresetData(props.modelValue))
const task = ref<PresetAssignment | 'test'>('npc')
const tasks = [
  ...imagePurposes,
  {
    id: 'simple' as const,
    label: 'Standard fallback',
    hint: 'For unassigned tasks using the standard ComfyUI profile.'
  },
  {
    id: 'advanced' as const,
    label: 'High-fidelity fallback',
    hint: 'For unassigned tasks using the high-fidelity ComfyUI profile.'
  },
  {
    id: 'test' as const,
    label: 'Test generation',
    hint: 'A single preset used by both ComfyUI test buttons. Its base workflow runs without a reference.'
  }
]
const purpose = computed(() => imagePurposes.find(item => item.id === task.value)?.id)
const profile = computed<'simple' | 'advanced'>(() => {
  const entry = imagePurposes.find(item => item.id === task.value)
  if (!entry) return task.value === 'advanced' ? 'advanced' : 'simple'
  return (props.settings[entry.quality] ?? entry.fallback) === 'simple' ? 'simple' : 'advanced'
})
const selected = computed(() =>
  task.value === 'test'
    ? (draft.value.comfyui_test_preset ?? '')
    : (draft.value.comfyui_assignments?.[task.value] ?? '')
)
function launch(): void {
  draft.value = clonePresetData(props.modelValue)
  open.value = true
}
function choose(id: string): void {
  if (task.value === 'test') {
    draft.value.comfyui_test_preset = id || null
    return
  }
  const assignments = { ...draft.value.comfyui_assignments }
  if (id) assignments[task.value] = id
  else delete assignments[task.value]
  draft.value.comfyui_assignments = assignments
}
function applyPreset(value: ComfyOptions): void {
  // Editing the library must not accidentally assign a different quality fallback.
  const assignments = Object.fromEntries(
    Object.entries(draft.value.comfyui_assignments ?? {}).filter(([, id]) => value.comfyui_presets?.[id])
  )
  draft.value = { ...value, comfyui_assignments: assignments }
  const id = value.comfyui_assignments?.[purpose.value ?? profile.value]
  if (id) choose(id)
  editing.value = false
}
function save(): void {
  emit('update:modelValue', draft.value)
  open.value = false
}
const editOptions = computed(() => ({
  ...draft.value,
  comfyui_assignments: {
    ...draft.value.comfyui_assignments,
    ...(selected.value ? { [purpose.value ?? profile.value]: selected.value } : {})
  }
}))
const invalid = computed(
  () =>
    Object.values(draft.value.comfyui_assignments ?? {}).some(
      id => !draft.value.comfyui_presets?.[id]
    ) ||
    Boolean(
      draft.value.comfyui_test_preset &&
      !draft.value.comfyui_presets?.[draft.value.comfyui_test_preset]
    )
)
</script>
<template>
  <section class="space-y-4 rounded-3xl border border-slate-700 bg-slate-900 p-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h3 class="font-bold text-white">3. Image tasks & presets</h3>
        <p class="mt-1 text-xs text-slate-400">
          Assign a style to each task, manage presets and choose the test preset.
        </p>
      </div>
      <button
        type="button"
        class="rounded-xl bg-cyan-700 px-4 py-2 text-sm text-white"
        @click="launch"
      >
        Manage presets & assignments
      </button>
    </div>
    <div class="flex flex-wrap gap-2">
      <span
        v-for="item in imagePurposes"
        :key="item.id"
        class="rounded-lg bg-slate-950 px-3 py-2 text-xs"
        :class="modelValue.comfyui_assignments?.[item.id] ? 'text-emerald-300' : 'text-slate-400'"
        :title="
          modelValue.comfyui_assignments?.[item.id]
            ? 'Preset assigned; compatibility is checked separately.'
            : 'No task preset; uses its quality profile.'
        "
        >{{ modelValue.comfyui_assignments?.[item.id] ? '✓' : '✕' }} {{ item.label }}</span
      >
    </div>
    <p class="text-xs text-slate-400">
      ✓ Assigned · ✕ Inherits quality profile. These indicators do not confirm server compatibility.
    </p>
    <ComfyDialog v-if="open" title="Image tasks & preset library" @close="open = false">
      <div class="grid gap-6 md:grid-cols-[220px_minmax(0,1fr)]">
        <nav
          aria-label="Image tasks"
          class="flex gap-2 overflow-x-auto md:flex-col md:overflow-visible"
        >
          <button
            v-for="item in tasks"
            :key="item.id"
            type="button"
            :aria-pressed="task === item.id"
            class="shrink-0 rounded-lg px-3 py-3 text-left text-sm"
            :class="
              task === item.id ? 'bg-cyan-900/50 text-cyan-200' : 'bg-slate-950 text-slate-400'
            "
            @click="task = item.id"
          >
            {{ item.label }}
          </button>
        </nav>
        <div class="min-w-0 space-y-5">
          <div>
            <h3 class="text-lg font-semibold">{{ tasks.find(item => item.id === task)?.label }}</h3>
            <p class="mt-1 text-sm text-slate-400">
              {{ tasks.find(item => item.id === task)?.hint }}
            </p>
          </div>
          <div class="flex flex-wrap items-center gap-3 rounded-lg border border-slate-700 p-3">
            <span class="flex-1 text-sm"
              >Selected:
              {{
                draft.comfyui_presets?.[selected]?.name ||
                (selected ? 'Unavailable preset' : 'None')
              }}</span
            ><button type="button" class="text-xs text-slate-300 underline" @click="choose('')">
              Clear assignment</button
            ><button
              type="button"
              class="rounded-lg bg-cyan-700 px-3 py-2 text-sm"
              @click="editing = true"
            >
              {{ selected ? 'Edit preset / create copy' : 'Create or edit presets' }}
            </button>
          </div>
          <p class="text-xs text-slate-400">
            Task labels guide selection. You can choose any compatible preset; selecting it here
            does not change its labels.
          </p>
          <ComfyPresetBrowser
            :presets="draft.comfyui_presets ?? {}"
            :selected="selected"
            @select="choose"
          />
        </div>
      </div>
      <template #footer
        ><p class="mr-auto text-xs text-slate-400">
          Apply here, then save Visuals Settings. Clearing a fallback requires another provider or a
          replacement preset.
        </p>
        <button type="button" class="px-3 py-2 text-sm" @click="open = false">
          Discard changes</button
        ><button
          type="button"
          :disabled="invalid"
          class="rounded-lg bg-cyan-700 px-4 py-2 text-sm disabled:opacity-40"
          @click="save"
        >
          Apply assignments
        </button></template
      >
      <ComfyPresetModal
        v-if="editing"
        :open="editing"
        :purpose="purpose"
        :profile="profile"
        :model-value="editOptions"
        :test-result="testResults[profile === 'simple' ? 'simple_v' : 'advanced_v']"
        @close="editing = false"
        @apply="applyPreset"
        @test="options => emit('test', { options, profile })"
      />
    </ComfyDialog>
  </section>
</template>
