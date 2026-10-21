<script setup lang="ts">
import { computed } from 'vue'

const APPEARANCE_MAX_LENGTH = 100

const props = defineProps<{
  modelValue: string | null | undefined
  targetType: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
}>()

const PLACEHOLDERS: Record<string, string> = {
  cover: 'ruined lighthouse, stormy sea, teal and amber, ominous',
  protagonist: 'lean young woman, short red hair, leather coat, brass goggles',
  npc: 'gaunt elderly man, white beard, ink-stained robe, round spectacles',
  object: 'small brass key, ornate bow, tarnished green patina',
}

const length = computed(() => (props.modelValue || '').length)
const label = computed(() => (props.targetType === 'cover' ? 'Cover Visual Keywords' : 'Appearance Keywords'))
const placeholder = computed(() => PLACEHOLDERS[props.targetType] || '')
</script>

<template>
  <div class="space-y-3">
    <div class="flex justify-between items-center">
      <label class="block text-xs font-black text-slate-500 uppercase tracking-widest">{{ label }}</label>
      <span :class="['text-xs font-bold tracking-widest', length > APPEARANCE_MAX_LENGTH ? 'text-red-500' : 'text-emerald-500/50']">
        {{ length }} / {{ APPEARANCE_MAX_LENGTH }}
      </span>
    </div>
    <input
      :value="modelValue || ''"
      :maxlength="APPEARANCE_MAX_LENGTH"
      :placeholder="placeholder"
      class="w-full bg-black/40 border border-white/5 rounded-2xl px-4 py-3 text-sm text-slate-300 focus:border-emerald-500 outline-none transition-all shadow-inner"
      @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
    <p class="text-[10px] text-slate-500 uppercase tracking-wider">
      Optional. Comma-separated visual keywords (English works best), added to the image generation prompt.
    </p>
  </div>
</template>
