<script setup lang="ts">
import { computed, getCurrentInstance, ref } from 'vue'

const props = defineProps<{ label: string; modelValue: string; files?: string[]; folder?: string }>()
const emit = defineEmits<{ (event: 'update:modelValue', value: string): void }>()
const manual = ref(false)
const controlId = `comfy-model-${getCurrentInstance()!.uid}`
const available = computed(() => props.files?.includes(props.modelValue))
const hasFiles = computed(() => Boolean(props.files?.length))
function change(event: Event): void {
  emit('update:modelValue', (event.target as HTMLInputElement | HTMLSelectElement).value)
}
</script>

<template>
  <div class="space-y-1 text-xs">
    <label :for="controlId" class="block text-slate-300">{{ label }}</label>
    <select v-if="hasFiles && !manual" :id="controlId" :value="modelValue" :aria-describedby="`${controlId}-help`" class="w-full min-w-0 rounded-lg border border-slate-700 bg-slate-900 p-2 text-slate-200" @change="change">
      <option v-if="!available" :value="modelValue">Not found: {{ modelValue || '(empty filename)' }}</option>
      <option v-for="file in files" :key="file" :value="file">{{ file }}</option>
    </select>
    <input v-else :id="controlId" :value="modelValue" :aria-describedby="`${controlId}-help`" class="w-full rounded-lg border border-slate-700 bg-slate-900 p-2 text-slate-200" @change="change" />
    <p :id="`${controlId}-help`" role="status" :class="files !== undefined && !available ? 'text-amber-300' : 'text-slate-400'">
      <template v-if="files === undefined">Refresh the model list to see installed files.</template>
      <template v-else-if="!hasFiles">No files reported by this loader. Check ComfyUI model search paths<span v-if="folder"> (usually {{ folder }})</span>, then refresh.</template>
      <template v-else-if="!available">The current filename is not available on this server. Choose an installed file from the list.</template>
      <template v-else>{{ files.length }} installed {{ files.length === 1 ? 'file' : 'files' }}. The selected filename is available.</template>
    </p>
    <button v-if="hasFiles" type="button" class="text-slate-400 underline" @click="manual = !manual">{{ manual ? 'Use installed model list' : 'Enter filename manually' }}</button>
  </div>
</template>
