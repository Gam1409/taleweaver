<script setup lang="ts">
import { computed, ref } from 'vue'
import { Globe2, ChevronRight } from 'lucide-vue-next'
import type { LivingWorldPreferences } from '@/services/livingWorld'
import ConcordiaSettingsModal from './ConcordiaSettingsModal.vue'
const props = defineProps<{ modelValue?: LivingWorldPreferences | null; existing?: boolean; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: LivingWorldPreferences]; save: [] }>()
const open = ref(false)
const enabled = computed(() => props.modelValue?.living_world_enabled && props.modelValue?.deliberation_enabled && props.modelValue?.decision_engine === 'concordia')
function apply(settings: LivingWorldPreferences): void {
  emit('update:modelValue', settings)
  open.value = false
  if (props.existing) emit('save')
}
</script>

<template>
  <button type="button" :disabled="disabled" class="flex w-full items-center gap-3 rounded-2xl border border-cyan-400/20 bg-cyan-400/5 px-4 py-3.5 text-left transition hover:border-cyan-400/50 hover:bg-cyan-400/10 disabled:opacity-40" @click="open = true">
    <Globe2 class="h-5 w-5 text-cyan-300" /><span class="flex-1"><span class="block text-sm font-black text-white">Living World</span><span class="text-[10px] font-bold uppercase tracking-widest text-white/40">Concordia · {{ enabled ? 'Enabled' : 'Disabled' }}</span></span><ChevronRight class="h-4 w-4 text-cyan-300" />
  </button>
  <ConcordiaSettingsModal v-if="open" :model-value="modelValue" :existing="existing" @close="open = false" @apply="apply" />
</template>
