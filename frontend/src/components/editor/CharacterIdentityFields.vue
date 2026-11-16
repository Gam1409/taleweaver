<script setup lang="ts">
defineProps<{ gender?: string | null; ageYears?: number | null; disabled?: boolean }>()
const emit = defineEmits<{
  'update:gender': [value: string | null]
  'update:ageYears': [value: number | null]
}>()
function saveAge(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.checkValidity()) { input.reportValidity(); return }
  emit('update:ageYears', input.value === '' ? null : input.valueAsNumber)
}
</script>

<template>
  <fieldset :disabled="disabled" class="grid grid-cols-1 gap-3 sm:grid-cols-2">
    <label class="space-y-1 text-xs text-slate-400">
      <span>Gender (optional)</span>
      <input :value="gender ?? ''" maxlength="80" placeholder="Not specified"
        class="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white"
        @change="emit('update:gender', ($event.target as HTMLInputElement).value.trim() || null)" />
    </label>
    <label class="space-y-1 text-xs text-slate-400">
      <span>Age in years (optional)</span>
      <input :value="ageYears ?? ''" type="number" min="0" max="100000" step="1" placeholder="Unknown"
        class="w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white"
        @change="saveAge" />
    </label>
    <p class="text-xs text-slate-500 sm:col-span-2">Character facts used by narration and images. Leave unknown values empty.</p>
  </fieldset>
</template>
