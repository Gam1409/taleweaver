<script setup lang="ts">
defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
</script>

<template>
  <details class="rounded-xl border border-white/10 bg-slate-950/30 p-4">
    <summary class="cursor-pointer text-sm font-semibold text-slate-200">Character cards</summary>
    <p class="mt-3 text-xs leading-relaxed text-slate-400">
      Portraits, descriptions and a short history of your encounters are available during play.
    </p>
    <label class="mt-3 flex cursor-pointer items-start gap-3 text-sm text-slate-200">
      <input
        type="checkbox"
        :checked="modelValue"
        class="mt-1 h-4 w-4 shrink-0 accent-amber-400"
        @change="emit('update:modelValue', ($event.target as HTMLInputElement).checked)"
      />
      <span>
        Show NPC state and relationship indicators
        <span class="mt-1 block text-xs leading-relaxed text-slate-400">
          Shows the last evaluated emotion, trust, affinity, respect and tension in VN cards.
          These are narrative estimates. Private inventories and plans stay hidden.
          You can change this later in Characters.
        </span>
      </span>
    </label>
  </details>
</template>
