<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Plus, X } from 'lucide-vue-next'
import { useDialogFocus } from '@/composables/useDialogFocus'
import type { ItemDraft } from '@/services/itemGeneration'
import ItemDraftGenerator from './ItemDraftGenerator.vue'

const props = defineProps<{
  adventureId: string
  scenes: { id: string; name?: string; label?: string }[]
  initialSceneId?: string | null
}>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'draft', draft: ItemDraft, sceneId: string): void
}>()
const dialog = ref<HTMLElement | null>(null)
const sceneId = ref('')
const itemType = ref('DEFAULT')
const busy = ref(false)
const types = ['DEFAULT', 'WEARABLE', 'CONSUMABLE', 'WEAPON', 'READABLE', 'CONTAINER', 'SWITCH', 'CONSTRUCTABLE']
const validScene = computed(() => props.scenes.some(scene => scene.id === sceneId.value))
const generationContext = computed(() => JSON.stringify([props.adventureId, sceneId.value]))
useDialogFocus(dialog, () => emit('close'))

watch(() => props.scenes.map(scene => scene.id), ids => {
  if (ids.includes(sceneId.value)) return
  sceneId.value = ids.includes(props.initialSceneId || '') ? props.initialSceneId! : (ids[0] || '')
}, { immediate: true, flush: 'sync' })
watch(() => props.adventureId, () => emit('close'), { flush: 'sync' })

function reviewDraft(draft: ItemDraft) {
  if (validScene.value) emit('draft', draft, sceneId.value)
}
</script>

<template>
  <Teleport to="body">
    <div ref="dialog" role="dialog" aria-modal="true" aria-labelledby="create-item-title" tabindex="-1"
      class="fixed inset-0 z-[260] flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4"
      @click.self="emit('close')">
      <div class="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl border border-emerald-500/30 bg-slate-900 p-6 shadow-2xl space-y-5">
        <div class="flex items-start justify-between gap-4">
          <h2 id="create-item-title" class="flex items-center gap-2 text-lg font-black text-white"><Plus class="h-5 w-5 text-emerald-400" />Add item</h2>
          <button type="button" aria-label="Close add item" class="rounded-full p-2 text-slate-400 hover:bg-white/10 hover:text-white" @click="emit('close')"><X class="h-5 w-5" /></button>
        </div>
        <p class="text-sm text-slate-400">Describe one item to generate its name, description and technical fields. Review the draft in the editor before saving it to this adventure.</p>
        <div class="grid gap-4 sm:grid-cols-2">
          <label class="space-y-2 text-sm text-slate-300">Location
            <select v-model="sceneId" :disabled="busy || !scenes.length" class="mt-2 w-full rounded-xl border border-white/10 bg-slate-950 p-3 text-white disabled:opacity-50">
              <option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ scene.name || scene.label || scene.id }}</option>
            </select>
          </label>
          <label class="space-y-2 text-sm text-slate-300">Item type
            <select v-model="itemType" :disabled="busy" class="mt-2 w-full rounded-xl border border-white/10 bg-slate-950 p-3 text-white disabled:opacity-50">
              <option v-for="type in types" :key="type" :value="type">{{ type }}</option>
            </select>
          </label>
        </div>
        <p v-if="!validScene" role="alert" class="text-sm text-amber-300">Add a scene to the adventure before creating an item.</p>
        <ItemDraftGenerator :key="generationContext" :adventure-id="adventureId" :item-type="itemType" :fixed-slots="[]"
          :disabled="!validScene" review-location="editor" @draft="reviewDraft" @busy="busy = $event" />
      </div>
    </div>
  </Teleport>
</template>
