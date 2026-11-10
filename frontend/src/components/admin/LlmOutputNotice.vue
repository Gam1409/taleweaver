<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ provider: string; responseFormat?: string }>()
const mode = computed(() => {
  if (props.provider === 'custom_openai') return props.responseFormat || 'prompt'
  if (props.provider === 'minimax') return 'prompt'
  return 'auto'
})
</script>

<template>
  <aside role="note" class="rounded-xl border border-amber-500/30 bg-amber-500/5 p-3 text-xs text-amber-200">
    <p class="font-bold">Technical output compatibility</p>
    <p v-if="mode === 'prompt'" class="mt-1">
      Prompt-only output: this connection relies on the model following the requested format.
      TaleWeaver checks the complete response locally before applying changes.
    </p>
    <p v-else-if="mode === 'json_object'" class="mt-1">
      JSON-only output: supporting servers enforce JSON syntax, while TaleWeaver checks fields,
      identifiers and game facts locally. Valid JSON can still contain an invalid decision.
    </p>
    <p v-else class="mt-1">
      Native schema support depends on the provider, model and server version. Incompatible task
      schemas use JSON-only output where supported, or prompt-only output otherwise. Some constraints
      are checked locally. A successful connection test does not certify every task schema.
    </p>
  </aside>
</template>
