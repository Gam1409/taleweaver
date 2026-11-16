<script setup lang="ts" generic="Key extends string">
import { editorSectionIcon } from '@/utils/editorNavigation'

defineProps<{
  modelValue: Key
  tabs: ReadonlyArray<{ key: Key; label: string }>
  sequenceCount: number
  validationText: string
  validationClass: string
}>()
const emit = defineEmits<{ 'update:modelValue': [key: Key] }>()
</script>

<template>
  <aside class="authoring-navigation">
    <div class="mb-5 lg:hidden">
      <label for="editor-section" class="mb-2 block text-sm text-slate-400">Editor section</label>
      <select id="editor-section" :value="modelValue" class="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-3 text-slate-200" @change="emit('update:modelValue', ($event.target as HTMLSelectElement).value as Key)">
        <option v-for="tab in tabs" :key="tab.key" :value="tab.key">{{ tab.label }}{{ tab.key === 'sequences' && sequenceCount > 0 ? ` (${sequenceCount})` : '' }}{{ tab.key === 'validation' && validationText ? ` (${validationText})` : '' }}</option>
      </select>
    </div>
    <nav class="authoring-section-nav hidden lg:block" aria-label="Adventure sections">
      <p class="px-3 pb-3 text-xs tracking-widest text-slate-500">Adventure</p>
      <button v-for="tab in tabs" :key="tab.key" type="button" class="authoring-section-button" :class="{ 'is-active': modelValue === tab.key }" :aria-current="modelValue === tab.key ? 'page' : undefined" @click="emit('update:modelValue', tab.key)">
        <component :is="editorSectionIcon(tab.key)" class="h-[18px] w-[18px] shrink-0" :stroke-width="1.5" aria-hidden="true" />
        <span class="min-w-0 flex-1">{{ tab.label }}</span>
        <span v-if="tab.key === 'sequences' && sequenceCount > 0" class="authoring-nav-count">{{ sequenceCount }}</span>
        <span v-if="tab.key === 'validation' && validationText" :class="['authoring-nav-count', validationClass]">{{ validationText }}</span>
      </button>
    </nav>
  </aside>
</template>
