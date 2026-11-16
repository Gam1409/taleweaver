<script setup lang="ts">
import { onMounted, ref } from 'vue'

defineProps<{ message: string }>()
defineEmits<{ retry: []; exit: [] }>()
const retryButton = ref<HTMLButtonElement | null>(null)
onMounted(() => retryButton.value?.focus())
</script>

<template>
  <div
    class="fixed inset-0 z-[220] flex items-center justify-center bg-slate-950/85 px-6 backdrop-blur-sm"
    role="alertdialog"
    aria-modal="true"
    aria-labelledby="session-load-title"
    aria-describedby="session-load-message"
  >
    <div class="w-full max-w-md rounded-2xl border border-amber-500/30 bg-slate-900 p-7 shadow-2xl">
      <h2 id="session-load-title" class="text-lg font-bold text-white">
        Session could not be loaded
      </h2>
      <p id="session-load-message" class="mt-3 text-sm leading-relaxed text-slate-300">
        {{ message }}
      </p>
      <div class="mt-6 flex flex-wrap gap-3">
        <button
          ref="retryButton"
          type="button"
          class="rounded-xl bg-cyan-600 px-4 py-2 font-bold text-white hover:bg-cyan-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-white"
          @click="$emit('retry')"
        >
          Try again
        </button>
        <button
          type="button"
          class="rounded-xl border border-slate-600 px-4 py-2 font-bold text-slate-200 hover:bg-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-white"
          @click="$emit('exit')"
        >
          Back to library
        </button>
      </div>
    </div>
  </div>
</template>
