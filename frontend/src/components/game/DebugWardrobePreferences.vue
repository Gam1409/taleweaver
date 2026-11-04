<script setup lang="ts">
import { computed, ref, watch } from 'vue'
export interface WardrobePreferences {
  detailed: boolean
  age_years: number | null
}
const props = defineProps<{ npcId: string; preferences: WardrobePreferences; busy: boolean }>()
const emit = defineEmits<{ command: [value: string] }>()
const detailed = ref(false)
const age = ref<number | ''>('')
watch(
  () => [props.npcId, props.preferences.detailed, props.preferences.age_years],
  () => {
    detailed.value = props.preferences.detailed
    age.value = props.preferences.age_years ?? ''
  },
  { immediate: true }
)
const valid = computed(
  () =>
    age.value === '' ||
    (typeof age.value === 'number' &&
      Number.isInteger(age.value) &&
      age.value >= 0 &&
      age.value <= 100000)
)
const dirty = computed(
  () =>
    detailed.value !== props.preferences.detailed ||
    (age.value === '' ? null : age.value) !== props.preferences.age_years
)
function save() {
  if (props.busy || !valid.value || !dirty.value) return
  emit(
    'command',
    `/debug wardrobe_settings ${JSON.stringify({ npc_id: props.npcId, expected: props.preferences, settings: { detailed: detailed.value, age_years: age.value === '' ? null : age.value } })}`
  )
}
</script>
<template>
  <section class="space-y-2 rounded border border-slate-700 p-3">
    <h4 class="font-bold">Recovery requirements</h4>
    <p>
      Saved clothing layer tracking: <strong>{{ preferences.detailed ? 'On' : 'Off' }}</strong> ·
      Recorded NPC age: <strong>{{ preferences.age_years ?? 'Unknown' }}</strong>
    </p>
    <p class="text-xs text-slate-400">
      Inner garments require layer tracking and a recorded adult age. This session's setting is
      separate from mature content and the adventure template.
    </p>
    <details>
      <summary class="cursor-pointer text-cyan-200">
        Edit this session's clothing settings and NPC age
      </summary>
      <form class="mt-3 space-y-3" @submit.prevent="save">
        <label class="flex items-start gap-2"
          ><input v-model="detailed" type="checkbox" :disabled="busy" class="mt-1" /> Enable
          clothing layer tracking for this session</label
        >
        <label class="block"
          >NPC age (years; blank means unknown)
          <input
            v-model.number="age"
            type="number"
            min="0"
            max="100000"
            step="1"
            :disabled="busy"
            class="mt-1 w-full rounded bg-slate-800 p-2"
          />
        </label>
        <p class="text-xs text-slate-400">
          Enter a known character-card age. Saving updates this session's NPC, leaves the template
          unchanged and invalidates the old recovery preview.
        </p>
        <button
          type="submit"
          :disabled="busy || !valid || !dirty"
          class="rounded bg-cyan-800 px-3 py-2 disabled:opacity-40"
        >
          Save wardrobe settings
        </button>
      </form>
    </details>
  </section>
</template>
