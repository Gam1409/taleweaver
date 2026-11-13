<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
const props = defineProps<{ modelValue: string[]; label: string; limit: number; characterLimit: number; disabled?: boolean; suggestions?: string[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()
const fields = ref<HTMLFieldSetElement>()
const choices = computed(() => (props.suggestions ?? []).filter(tag => !props.modelValue.includes(tag)))
function update(index: number, value: string) {
  emit('update:modelValue', props.modelValue.map((tag, i) => i === index ? value : tag))
}
async function add() {
  if (props.disabled || props.modelValue.length >= props.limit) return
  const index = props.modelValue.length
  emit('update:modelValue', [...props.modelValue, ''])
  await nextTick()
  fields.value?.querySelectorAll('textarea')[index]?.focus()
}
function addSaved(event: Event) {
  const select = event.target as HTMLSelectElement, value = select.value
  select.value = ''
  if (props.disabled || props.modelValue.length >= props.limit || !choices.value.includes(value)) return
  emit('update:modelValue', [...props.modelValue, value])
}
</script>
<template>
  <fieldset ref="fields" :disabled="disabled" :aria-label="label" class="space-y-2">
    <legend>{{ label }}</legend>
    <ul class="space-y-2"><li v-for="(tag, index) in modelValue" :key="index" class="flex items-end gap-2">
      <label class="min-w-0 flex-1">Tag {{ index + 1 }}<textarea :value="tag" rows="1" required :maxlength="characterLimit" @input="update(index, ($event.target as HTMLTextAreaElement).value)" /></label>
      <button type="button" class="world-info-button" :aria-label="`Remove tag ${index + 1}`" @click="emit('update:modelValue', modelValue.filter((_, i) => i !== index))">Remove</button>
    </li></ul>
    <button type="button" class="world-info-button" :disabled="modelValue.length >= limit" @click="add">Add tag</button>
    <label v-if="choices.length">Add a saved tag<select aria-label="Add a saved tag" :disabled="modelValue.length >= limit" @change="addSaved"><option value="">Choose an exact saved tag</option><option v-for="tag in choices" :key="tag" :value="tag">{{ tag }}</option></select></label>
    <small class="block text-xs text-slate-400">Up to {{ limit }} tags, {{ characterLimit }} characters each. Each field is one exact tag; spaces, commas and # are kept.</small>
  </fieldset>
</template>
