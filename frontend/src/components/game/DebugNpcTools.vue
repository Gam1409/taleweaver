<script setup lang="ts">
import { ref } from 'vue'
import DebugNpcClothing from './DebugNpcClothing.vue'

type ClothingNpc = InstanceType<typeof DebugNpcClothing>['$props']['npc']
const props = defineProps<{
  npc: ClothingNpc & { current_scene_id: string }
  scenes: { id: string; label: string }[]
  currentSceneId: string
  busy: boolean
}>()
const emit = defineEmits<{ command: [value: string] }>()
const destination = ref('')
function move(target: string) {
  if (!target || props.busy) return
  emit('command', `/debug move_npc ${JSON.stringify(props.npc.id)} ${JSON.stringify(target)}`)
}
</script>
<template>
  <div class="space-y-2">
    <details class="rounded-xl border border-slate-700 bg-slate-950/60 p-3 text-xs text-slate-200">
      <summary class="cursor-pointer font-bold text-cyan-300">Location</summary>
      <div class="mt-3 space-y-3">
        <p class="text-[11px] text-slate-400">
          Manual corrections affect this session only. Moving bypasses travel restrictions;
          visibility and health stay unchanged.
        </p>
        <label class="block"
          >Destination
          <select
            v-model="destination"
            class="mt-1 w-full rounded bg-slate-800 p-2"
            :disabled="busy"
          >
            <option value="">Select location</option>
            <option v-for="scene in scenes" :key="scene.id" :value="scene.id">
              {{ scene.label }} [{{ scene.id }}]
            </option>
          </select>
        </label>
        <div class="flex flex-wrap gap-2">
          <button
            type="button"
            class="rounded bg-cyan-900 px-3 py-2 disabled:opacity-40"
            :disabled="busy || !destination || destination === npc.current_scene_id"
            @click="move(destination)"
          >
            Move NPC
          </button>
          <button
            type="button"
            class="rounded bg-slate-700 px-3 py-2 disabled:opacity-40"
            :disabled="busy || !currentSceneId || currentSceneId === npc.current_scene_id"
            @click="move(currentSceneId)"
          >
            Bring to player
          </button>
        </div>
      </div>
    </details>
  </div>
</template>
