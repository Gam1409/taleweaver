<script setup lang="ts">
defineProps<{
  ready: boolean
  previewing: boolean
  example: string
  preview: { positive: string; negative: string } | null
  loading: boolean
  testResult?: { status: string; message: string; image_url?: string }
}>()
const emit = defineEmits<{
  (event: 'update:example', value: string): void
  (event: 'preview'): void
  (event: 'generate'): void
}>()
</script>
<template>
  <div class="grid items-start gap-5 lg:grid-cols-2">
    <div class="space-y-4 rounded-xl border border-slate-700 bg-slate-950/40 p-5">
      <h4 class="text-sm font-semibold">Prompt preview</h4>
      <p class="text-xs text-slate-400">Preview and test generation use the base workflow without a reference image. Reference rules apply when an image is supplied by the task.</p>
      <label class="block text-xs text-slate-400"
        >Example description<textarea
          :value="example"
          @input="emit('update:example', ($event.target as HTMLTextAreaElement).value)"
          maxlength="12000"
          rows="5"
          class="mt-2 block w-full rounded-lg border border-slate-600 bg-slate-900 p-3 text-sm text-slate-200"
        />
      </label>
      <button
        type="button"
        :disabled="!ready || previewing"
        class="primary-button"
        @click="emit('preview')"
      >
        {{ previewing ? 'Preparing…' : 'Preview prompt' }}
      </button>
      <p class="text-xs text-slate-400">
        Uses the Small / Utility LLM when adaptation is enabled. Does not generate an image.
      </p>
      <div v-if="preview" aria-live="polite" class="space-y-3 text-sm">
        <p class="whitespace-pre-wrap break-words">{{ preview.positive }}</p>
        <p v-if="preview.negative" class="whitespace-pre-wrap break-words text-slate-400">
          Negative: {{ preview.negative }}
        </p>
      </div>
    </div>
    <div class="space-y-4 rounded-xl border border-slate-700 bg-slate-950/40 p-5">
      <h4 class="text-sm font-semibold">Test image</h4>
      <p class="text-sm leading-relaxed text-slate-400">
        Uses the example description on the left, reusing its current prepared preview when available. Runs this window's draft settings and does not save your changes.
      </p>
      <button
        type="button"
        :disabled="!ready || loading || previewing"
        class="primary-button"
        @click="emit('generate')"
      >
        {{ loading ? 'Generating…' : 'Generate test image' }}
      </button>
      <div v-if="testResult" aria-live="polite" class="space-y-3">
        <p
          class="text-sm whitespace-pre-wrap break-words"
          :class="testResult?.status === 'error' ? 'text-rose-300' : 'text-slate-300'"
        >
          {{ testResult?.message }}
        </p>
        <img
          v-if="testResult?.image_url"
          :src="testResult.image_url"
          alt="Preset test result"
          class="max-h-72 w-full rounded-lg object-contain"
        />
      </div>
    </div>
  </div>
</template>
<style scoped>
.primary-button {
  @apply rounded-lg bg-cyan-700 px-4 py-2.5 text-sm font-medium text-white hover:bg-cyan-600 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline focus-visible:outline-cyan-400;
}
</style>
