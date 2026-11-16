<script setup lang="ts">
defineProps<{ updates: Record<string, unknown> }>()
function display(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}
</script>

<template>
  <details class="mt-2 text-xs text-slate-400" @click.stop>
    <summary class="cursor-pointer">Review field changes</summary>
    <dl class="mt-2 space-y-2">
      <div v-for="(value, field) in updates" :key="field">
        <dt class="font-semibold text-violet-200">{{ field }}</dt>
        <dd class="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded bg-black/20 p-2 text-slate-300">{{ display(value) }}</dd>
      </div>
    </dl>
  </details>
</template>
