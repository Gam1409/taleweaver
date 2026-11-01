<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { apiFetch } from '@/services/http'

type NarrationPace = 'leisurely' | 'balanced' | 'brisk'
type VisualPreparation = 'legacy' | 'plan'
type AuditFailure = 'block' | 'warn'
type NarrationSettings = {
  pace: NarrationPace
  scene_staging?: boolean
  visual_preparation?: VisualPreparation
  visual_audit?: boolean
  visual_audit_failure?: AuditFailure
}
const props = defineProps<{ sessionId: string }>()
const pace = ref<NarrationPace>('balanced')
const savedPace = ref<NarrationPace>('balanced')
const sceneStaging = ref(false)
const savedSceneStaging = ref(false)
const visualPreparation = ref<VisualPreparation>('legacy')
const savedVisualPreparation = ref<VisualPreparation>('legacy')
const visualAudit = ref(true)
const savedVisualAudit = ref(true)
const auditFailure = ref<AuditFailure>('block')
const savedAuditFailure = ref<AuditFailure>('block')
const loaded = ref(false)
const busy = ref(false)
const error = ref('')
let controller: AbortController | null = null
const options: { value: NarrationPace; label: string; description: string }[] = [
  {
    value: 'leisurely',
    label: 'Leisurely',
    description: 'Linger on reactions, small gestures, and quiet moments.'
  },
  {
    value: 'balanced',
    label: 'Balanced',
    description: 'One meaningful exchange, with room for your response.'
  },
  {
    value: 'brisk',
    label: 'Brisk',
    description: 'Move through routine moments; pause at meaningful decisions.'
  }
]

async function load(): Promise<void> {
  controller?.abort()
  const request = new AbortController()
  controller = request
  loaded.value = false
  busy.value = true
  error.value = ''
  const timeout = window.setTimeout(() => request.abort(), 15000)
  try {
    const response = await apiFetch(
      `/adventures/${encodeURIComponent(props.sessionId)}/vn-settings`,
      { signal: request.signal }
    )
    if (!response.ok) throw new Error('Could not load narration settings.')
    const data = (await response.json()) as { settings: NarrationSettings }
    if (controller !== request) return
    pace.value = options.some(option => option.value === data.settings.pace)
      ? data.settings.pace
      : 'balanced'
    savedPace.value = pace.value
    sceneStaging.value = data.settings.scene_staging ?? false
    savedSceneStaging.value = sceneStaging.value
    visualPreparation.value = data.settings.visual_preparation === 'plan' ? 'plan' : 'legacy'
    savedVisualPreparation.value = visualPreparation.value
    visualAudit.value = data.settings.visual_audit ?? true
    savedVisualAudit.value = visualAudit.value
    auditFailure.value = data.settings.visual_audit_failure === 'warn' ? 'warn' : 'block'
    savedAuditFailure.value = auditFailure.value
    loaded.value = true
  } catch (cause) {
    if (controller === request)
      error.value =
        cause instanceof Error && cause.name !== 'AbortError'
          ? cause.message
          : 'Loading narration settings timed out. Please retry.'
  } finally {
    window.clearTimeout(timeout)
    if (controller === request) busy.value = false
  }
}

async function save(): Promise<boolean> {
  // An unopened or failed settings request must not overwrite the server default.
  if (!loaded.value || (
    pace.value === savedPace.value && sceneStaging.value === savedSceneStaging.value &&
    visualPreparation.value === savedVisualPreparation.value &&
    visualAudit.value === savedVisualAudit.value && auditFailure.value === savedAuditFailure.value
  )) return true
  if (busy.value) return false
  controller?.abort()
  const request = new AbortController()
  controller = request
  busy.value = true
  error.value = ''
  const timeout = window.setTimeout(() => request.abort(), 15000)
  try {
    const response = await apiFetch(
      `/adventures/${encodeURIComponent(props.sessionId)}/vn-settings`,
      {
        method: 'PATCH',
        includeJson: true,
        signal: request.signal,
        body: JSON.stringify({
          pace: pace.value,
          scene_staging: sceneStaging.value,
          visual_preparation: visualPreparation.value,
          visual_audit: visualAudit.value,
          visual_audit_failure: auditFailure.value,
        })
      }
    )
    if (response.status === 409) {
      const data = (await response.json().catch(() => null)) as { detail?: unknown } | null
      throw new Error(
        typeof data?.detail === 'string' && data.detail.trim()
          ? data.detail
          : 'Wait for the current reply to finish, then save again.'
      )
    }
    if (!response.ok) throw new Error('Could not save narration settings. Please retry.')
    if (controller !== request) return false
    savedPace.value = pace.value
    savedSceneStaging.value = sceneStaging.value
    savedVisualPreparation.value = visualPreparation.value
    savedVisualAudit.value = visualAudit.value
    savedAuditFailure.value = auditFailure.value
    return true
  } catch (cause) {
    if (controller === request)
      error.value =
        cause instanceof Error && cause.name !== 'AbortError'
          ? cause.message
          : 'Saving narration settings timed out. Please retry.'
    return false
  } finally {
    window.clearTimeout(timeout)
    if (controller === request) busy.value = false
  }
}

watch(
  () => props.sessionId,
  () => {
    void load()
  },
  { immediate: true }
)
onBeforeUnmount(() => {
  controller?.abort()
  controller = null
})
defineExpose({ save })
</script>

<template>
  <details class="rounded-2xl border border-rose-400/20 bg-rose-400/5 p-4">
    <summary class="cursor-pointer font-semibold text-rose-200">Visual novel narration</summary>
    <p class="mt-3 text-xs text-slate-400">
      Pace changes how a scene unfolds. Your character's decisions remain yours. Changes apply to
      future replies.
    </p>
    <p v-if="busy" role="status" class="mt-3 text-sm text-slate-400">
      Loading or saving narration settings…
    </p>
    <p v-if="error" role="alert" class="mt-3 text-sm text-rose-300">
      {{ error }}
      <button v-if="!loaded" type="button" class="underline" @click="load">Retry</button>
    </p>
    <fieldset :disabled="!loaded || busy" class="mt-3 space-y-2 disabled:opacity-50">
      <legend class="mb-2 text-sm font-semibold">Narration pace</legend>
      <label
        v-for="option in options"
        :key="option.value"
        class="flex cursor-pointer items-start gap-3 rounded-xl border border-white/10 p-3 hover:bg-white/5"
      >
        <input
          v-model="pace"
          type="radio"
          name="vn-narration-pace"
          :value="option.value"
          class="mt-1 accent-rose-400"
        />
        <span
          ><span class="block text-sm font-semibold">{{ option.label }}</span
          ><span class="text-xs text-slate-400">{{ option.description }}</span></span
        >
      </label>
      <label class="flex items-start gap-3 rounded-xl border border-white/10 p-3">
        <input v-model="sceneStaging" type="checkbox" class="mt-1 accent-rose-400" />
        <span>
          <span class="block text-sm font-semibold">Track scene poses and placement (experimental)</span>
          <span class="text-xs text-slate-400">After each reply, check explicit pose and placement changes for continuity and illustrations. Adds one Small / Utility request before the turn finishes. Clothing and inventory remain controlled by the game rules.</span>
        </span>
      </label>
      <div class="space-y-3 rounded-xl border border-white/10 p-3">
        <label class="block text-sm font-semibold">
          Illustration preparation
          <select v-model="visualPreparation" class="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 p-2 text-sm">
            <option value="legacy">Current preparation</option>
            <option value="plan">Saved visual plan (experimental)</option>
          </select>
        </label>
        <p class="text-xs text-slate-400">The experimental path translates saved scene facts once and reuses them for later illustrations with the same settings. Your selected image prompt format is preserved.</p>
        <p class="text-xs text-slate-400">Saved visual plans currently support neutral scene continuity only. Sessions with NSFW enabled must use Current preparation (legacy).</p>
        <div v-if="visualPreparation === 'plan'" class="space-y-3">
          <label class="flex items-start gap-3 text-sm">
            <input v-model="visualAudit" type="checkbox" class="mt-1 accent-rose-400" />
            <span>Check visual continuity before the first image from each saved plan</span>
          </label>
          <p class="text-xs text-slate-400">The check adds one Small / Utility request for a new plan. It can miss mistakes and does not guarantee the generated image matches the scene. Some sessions always require this check.</p>
          <label class="block text-sm font-semibold">
            If the check fails or cannot finish
            <select v-model="auditFailure" class="mt-2 w-full rounded-lg border border-slate-600 bg-slate-900 p-2 text-sm">
              <option value="block">Keep the previous image and stop</option>
              <option value="warn">Generate with a visible warning</option>
            </select>
          </label>
        </div>
      </div>
    </fieldset>
  </details>
</template>
