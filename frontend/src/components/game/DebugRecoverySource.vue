<script setup lang="ts">
import { computed, watch } from 'vue'

const props = defineProps<{
  modelValue: string
  sources: Record<string, string>
  sourceRoles?: Record<string, string>
  disabled?: boolean
  expanded?: boolean
  label?: string
}>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
  quote: [value: string]
}>()
const source = computed(() => props.sources[props.modelValue] || '')
watch(
  () => props.modelValue,
  () => emit('quote', '')
)
function captureSelection(event: Event) {
  const element = event.currentTarget as HTMLElement
  const selection = window.getSelection()
  const range = selection?.rangeCount === 1 ? selection.getRangeAt(0) : null
  emit('quote', range && element.contains(range.commonAncestorContainer) ? range.toString() : '')
}
</script>

<template>
  <div class="min-w-0 space-y-2">
    <label class="block text-sm">
      {{ label || 'Source message' }}
      <select
        :value="modelValue"
        :disabled="disabled"
        class="mt-1 w-full min-w-0 rounded bg-slate-800 p-2"
        @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value)"
      >
        <option value="" disabled>Select a message</option>
        <option v-for="(text, id) in sources" :key="id" :value="id">
          {{ sourceRoles?.[id] === 'user' ? 'Player' : 'Narrator' }} · {{ text.slice(0, 100) }} ·
          {{ id }}
        </option>
      </select>
    </label>
    <p v-if="sourceRoles?.[modelValue] === 'user'" class="text-xs text-amber-200">
      Player message — requires your explicit confirmation in Debug.
    </p>
    <details v-if="source" :open="expanded" class="rounded bg-slate-900 p-2">
      <summary class="cursor-pointer text-cyan-200">
        Original {{ sourceRoles?.[modelValue] === 'user' ? 'player' : 'assistant' }} message —
        compare the exact wording
      </summary>
      <pre
        class="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words font-sans text-xs select-text"
        @mouseup="captureSelection"
        @keyup="captureSelection"
        >{{ source }}</pre>
    </details>
    <p v-else class="text-xs text-amber-200">Choose a message from the reviewed history.</p>
  </div>
</template>
