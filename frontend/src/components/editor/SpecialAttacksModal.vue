<script setup lang="ts">
import { X } from 'lucide-vue-next'
import type { SpecialAttack } from '@/types'
import SpecialAttacksEditor from './SpecialAttacksEditor.vue'

defineProps<{
  open: boolean
  adventureId: string
  npc: { id: string; name: string; metadata_json?: { special_actions?: SpecialAttack[] } | null } | null
}>()

const emit = defineEmits<{
  close: []
  saved: [attacks: SpecialAttack[]]
}>()
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open && npc"
      class="fixed inset-0 z-[300] bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      :aria-label="`Special attacks of ${npc.name}`"
      @click.self="emit('close')"
    >
      <div class="w-full max-w-3xl max-h-[88vh] overflow-y-auto bg-slate-900 border border-white/10 rounded-3xl shadow-2xl p-6 space-y-4">
        <div class="flex items-center justify-between">
          <h3 class="text-sm font-black text-white uppercase tracking-[0.2em]">Combat Specials</h3>
          <button type="button" class="p-1.5 rounded-full text-slate-400 hover:text-white hover:bg-white/10" aria-label="Close" @click="emit('close')">
            <X class="w-4 h-4" />
          </button>
        </div>
        <p class="text-xs text-slate-400">
          NPCs use these during fights when they can pay the cost. Heals are favoured when the NPC is badly hurt.
        </p>
        <SpecialAttacksEditor
          :adventure-id="adventureId"
          target-type="npc"
          :target-id="npc.id"
          :owner-name="npc.name"
          :attacks="npc.metadata_json?.special_actions ?? []"
          @saved="(attacks) => emit('saved', attacks)"
        />
      </div>
    </div>
  </Teleport>
</template>
