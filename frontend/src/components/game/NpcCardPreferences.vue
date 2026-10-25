<script setup lang="ts">
import type { NpcCardSettingsController } from '@/composables/useNpcCardSettings'

defineProps<{ settings: NpcCardSettingsController }>()
</script>

<template>
  <details class="rounded-xl border border-slate-700 p-3 text-sm">
    <summary class="cursor-pointer font-semibold focus-visible:outline-amber-300">Character card display</summary>
    <label class="mt-3 flex items-start gap-3 cursor-pointer">
      <input type="checkbox" :checked="settings.showState.value" :disabled="settings.saving.value || !settings.loaded.value"
        class="mt-1 accent-amber-400" @change="settings.setShowState(($event.target as HTMLInputElement).checked)" />
      <span>
        <span class="block font-medium">Show VN relationship indicators</span>
        <span class="mt-1 block text-xs text-slate-400">Show last evaluated relationship and emotion estimates for this session. Learned history stays visible either way.</span>
      </span>
    </label>
    <p v-if="settings.saving.value" role="status" class="mt-2 text-xs text-slate-400">Updating display settings…</p>
    <p v-if="settings.error.value" role="alert" class="mt-2 text-xs text-rose-300">{{ settings.error.value }} <button type="button" class="underline" :disabled="settings.saving.value" @click="settings.refresh()">Reload settings</button></p>
  </details>
</template>
