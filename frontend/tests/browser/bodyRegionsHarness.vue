<script setup lang="ts">
import { onMounted, ref } from 'vue'
import NpcCurrentState from '../../src/components/game/NpcCurrentState.vue'
import type { NpcCurrentState as CurrentState } from '../../src/types/npcCurrentState'

const dialog = ref<HTMLDialogElement>()
const keys = ['BodyVaginal', 'BodyAnal', 'BodyUterine', 'BodyPenile']
const state = ref<CurrentState>({
  availability: 'present', game_minute: 480, layout: { form: 'humanoid', silhouette: 'neutral' },
  clothing: { status: 'available', detail_limited: false, placement_status: 'available', placement_slots: keys.map((key, i) => ({ key, status: i === 1 ? 'unconfirmed' : i === 3 ? 'occupied' : 'empty' })), items: [
    { item_id: 'glove', name: 'Black glove', slots: ['Hands'], description: 'A work glove.', layer: 1, visible_regions: [], uncovered_regions: [], image_url: null, current_state: [{ dimension: 'fabric', detail: 'The cuff is torn.' }] },
    { item_id: 'sensor', name: 'Sealed sensor', slots: ['BodyPenile'], description: '', layer: 0, visible_regions: [], uncovered_regions: [], image_url: null },
  ] },
  conditions: { status: 'available', items: [
    { id: 'wound', target_id: 'NPC', kind: 'injury', part: 'hand', detail: 'A recorded cut on the hand.', status: 'active', observation: 'recorded', last_changed_minute: 470, display_slots: ['Hands'] },
    { id: 'dust', target_id: 'glove', target_name: 'Black glove', kind: 'contamination', part: 'fabric', detail: 'Dust coats the glove.', status: 'active', observation: 'recorded', last_changed_minute: 470 },
    { id: 'medical', target_id: 'NPC', kind: 'other', part: 'uterus', detail: 'A source-confirmed medical observation.', status: 'active', observation: 'recorded', last_changed_minute: 475, display_slots: ['BodyUterine'] },
  ] },
})
function unknown() { state.value = { ...state.value, clothing: { status: 'available', detail_limited: false, items: [], placement_status: 'unassessed', placement_slots: [] }, conditions: { status: 'available', items: [] } } }
onMounted(() => dialog.value?.showModal())
</script>
<template>
  <dialog ref="dialog" class="npc-card-refined m-auto overflow-hidden border text-slate-100 font-ui" aria-label="Fictional character state" @cancel.prevent>
    <div class="flex h-full min-h-0 flex-col">
      <header class="flex flex-wrap items-center justify-between gap-3 border-b"><div><h2>Character state · fictional example</h2><p class="text-xs text-slate-400">Canonical items and confirmed observations</p></div><button type="button" class="rounded border border-slate-600 px-3 py-2 text-xs" @click="unknown">Unassessed layout</button></header>
      <main class="min-h-0 flex-1 overflow-y-auto p-5"><NpcCurrentState :state="state" compact /></main>
    </div>
  </dialog>
</template>
<style scoped src="../../src/components/game/NpcPortraitRefined.css"></style>
