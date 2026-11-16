<script setup lang="ts">
import { visualJobProgress } from '@/services/visualJobProgress'
</script>

<template>
  <aside v-if="Object.keys(visualJobProgress).length" aria-label="Image generation progress" role="status"
    class="pointer-events-none fixed bottom-24 right-3 z-50 max-w-[min(22rem,calc(100vw-1.5rem))] space-y-1 rounded-lg border border-slate-700/60 bg-slate-950/90 px-3 py-2 text-xs text-slate-300 shadow-lg">
    <p v-for="(label, id) in visualJobProgress" :key="id">{{ label }}</p>
  </aside>
</template>
