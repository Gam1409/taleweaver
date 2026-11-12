<script setup lang="ts">
import { Plus, Sparkles, Compass, Loader2 } from 'lucide-vue-next'
defineProps<{ isSeeding?: boolean }>()
defineEmits<{ create: []; 'generate-world': []; 'import-samples': [] }>()
</script>

<template>
  <div class="portal-creation-toolbar" aria-label="Create adventures">
    <button type="button" class="workspace-button workspace-primary" @click="$emit('create')"><Plus aria-hidden="true" />New adventure</button>
    <button type="button" class="workspace-button" @click="$emit('generate-world')"><Sparkles aria-hidden="true" />Generate world</button>
    <button type="button" class="workspace-button" :disabled="isSeeding" @click="$emit('import-samples')">
      <Loader2 v-if="isSeeding" class="animate-spin" aria-hidden="true" /><Compass v-else aria-hidden="true" />
      {{ isSeeding ? 'Importing samples…' : 'Import samples' }}
    </button>
  </div>
</template>
