<script setup lang="ts">
defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
</script>

<template>
  <details class="rounded-xl border border-white/10 bg-slate-950/30 p-4">
    <summary class="cursor-pointer text-sm font-semibold text-slate-200">Appearance and clothing</summary>
    <label class="mt-3 flex cursor-pointer items-start gap-3 text-sm">
      <input type="checkbox" :checked="modelValue" class="mt-1 h-4 w-4 shrink-0 accent-pink-400"
        @change="emit('update:modelValue', ($event.target as HTMLInputElement).checked)" />
      <span>
        <span class="font-medium text-pink-300">Mature content</span>
        <span class="mt-1 block text-xs leading-relaxed text-slate-400">Off: general outfits. On: clothing layers, including underlayers, for clearly adult characters. Your character’s clothing appears in their sheet and changes through actions in the story.</span>
      </span>
    </label>
  </details>
</template>
