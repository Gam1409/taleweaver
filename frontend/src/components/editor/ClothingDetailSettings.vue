<script setup lang="ts">
defineProps<{
  modelValue: boolean
  savedValue: boolean
  isSaving: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  save: []
}>()
</script>

<template>
  <section class="rounded-2xl border border-pink-400/20 bg-slate-950/30 p-5">
    <label class="flex items-start gap-3 text-sm">
      <input
        type="checkbox"
        :checked="modelValue"
        :disabled="isSaving"
        class="mt-1 h-4 w-4 shrink-0 accent-pink-400"
        @change="emit('update:modelValue', ($event.target as HTMLInputElement).checked)"
      />
      <span>
        <span class="font-semibold text-pink-300">Mature content</span>
        <span class="mt-2 block text-xs leading-relaxed text-slate-400">
          Track clothing layers, including underlayers, for clearly adult characters. Save to
          prepare missing appearance and clothing fields from known character details and owned
          items. Preparation uses your Utility model and can take a few minutes.
        </span>
      </span>
    </label>
    <p class="mt-3 text-xs leading-relaxed text-slate-400">
      Turning this off disables detailed tracking without deleting possessions or history. Changes
      apply to this adventure and new games; existing saved sessions keep their settings.
    </p>
    <div class="mt-4 flex flex-wrap items-center gap-3">
      <button
        type="button"
        :disabled="isSaving || modelValue === savedValue"
        class="rounded-xl bg-emerald-600 px-4 py-2 text-xs font-bold text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
        @click="emit('save')"
      >
        {{
          isSaving
            ? modelValue && !savedValue
              ? 'Preparing character details…'
              : 'Saving settings…'
            : 'Save clothing settings'
        }}
      </button>
      <span class="text-xs text-slate-400" role="status" aria-live="polite">
        {{ modelValue !== savedValue ? 'Unsaved changes' : savedValue ? 'Enabled' : 'Disabled' }}
      </span>
    </div>
  </section>
</template>
