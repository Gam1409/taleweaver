<script setup lang="ts">
import { ref } from 'vue'
import { configState } from '@/store/config'
import LicensesModal from './LicensesModal.vue'

const licensesOpen = ref(false)
</script>

<template>
  <footer class="workspace-footer mt-8 sm:mt-10 py-8 border-t border-white/5 text-center">
    <p class="text-[10px] font-bold text-slate-500 uppercase tracking-widest">
      © 2026 Anton Kuprin (fork of TaleWeaver by Jean Schmitz) • Released under MIT License • TaleWeaver v{{ configState.appVersion }}
    </p>
    <button type="button" class="mt-2 rounded px-2 py-1 text-xs text-slate-400 underline decoration-slate-600 underline-offset-4 hover:text-amber-200" aria-haspopup="dialog" @click="licensesOpen = true">Licenses</button>
    <LicensesModal v-if="licensesOpen" @close="licensesOpen = false" />
  </footer>
</template>
