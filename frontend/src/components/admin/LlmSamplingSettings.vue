<script setup lang="ts">
import { computed } from 'vue'
import SamplingFields from './SamplingFields.vue'
import SamplingHelp from './SamplingHelp.vue'
import {
  effectiveSampling,
  normalizeSampling,
  toggleRoleSampling,
  type SamplingProfile,
  type SamplingSettings
} from '@/services/llmSampling'
import type { LLMRole } from '@/services/llmRoleEndpoints'

const props = defineProps<{
  modelValue: SamplingSettings
  provider?: string
  role?: LLMRole
  embedded?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: SamplingSettings] }>()
const current = computed(() => normalizeSampling(props.modelValue))
const own = computed(() => (props.role ? !!current.value.roles[props.role]?.enabled : true))
const profile = computed(() =>
  props.role ? effectiveSampling(current.value, props.role) : current.value.defaults
)
function update(profile: SamplingProfile) {
  const next = normalizeSampling(current.value)
  if (props.role) next.roles[props.role] = { enabled: true, profile }
  else next.defaults = profile
  emit('update:modelValue', next)
}
function toggle(event: Event) {
  if (props.role)
    emit(
      'update:modelValue',
      toggleRoleSampling(current.value, props.role, (event.target as HTMLInputElement).checked)
    )
}
</script>

<template>
  <component
    :is="embedded ? 'section' : 'details'"
    :data-sampling-role="role || 'shared'"
    :class="embedded ? '' : 'rounded-xl border border-purple-700/40 p-4'"
  >
    <summary v-if="!embedded" class="cursor-pointer text-xs font-bold text-purple-300">
      {{ role ? 'Fine tuning — this role' : 'Shared generation defaults' }}
    </summary>
    <div class="mt-3 space-y-3">
      <div class="flex items-center justify-between gap-2">
        <p class="text-xs text-slate-300">Sampling controls</p>
        <SamplingHelp
          :id="`sampling-${role || 'shared'}-overview`"
          label="sampling controls"
          text="Sampling decides which next tokens the model may choose. Narrative prose can benefit from more variation; JSON extraction and technical tasks often benefit from more conservative choices. Higher settings do not automatically improve quality or make NPCs independent. Change one control at a time and compare the same scene."
        />
      </div>
      <label v-if="role" class="flex items-center gap-2 text-xs text-slate-300">
        <input type="checkbox" :checked="own" class="accent-purple-400" @change="toggle" />
        Use an independent sampling profile for this role
      </label>
      <p v-if="role && !own" class="text-xs text-slate-400">
        This role follows shared generation defaults. Enabling an independent profile first copies
        those values; later changes remain separate.
      </p>
      <template v-if="own">
        <p v-if="role" class="text-xs text-slate-400">
          Blank fields in this independent profile use server defaults. They do not inherit shared
          values.
        </p>
        <SamplingFields
          :model-value="profile"
          :provider="provider || 'shared'"
          :id="`sampling-${role || 'shared'}`"
          @update:model-value="update"
        />
      </template>
    </div>
  </component>
</template>
