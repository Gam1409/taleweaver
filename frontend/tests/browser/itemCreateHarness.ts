import { createApp, h, ref } from 'vue'
import '../../src/assets/main.css'
import ItemsTab from '../../src/components/editor/ItemsTab.vue'
import ItemCreateDialog from '../../src/components/editor/ItemCreateDialog.vue'
import { itemDraftFields } from '../../src/services/itemDraftFields'
import type { ItemDraft } from '../../src/services/itemGeneration'

createApp({
  setup() {
    const open = ref(false), initialScene = ref<string | null>(null)
    const scenes = ref([{ id: 'HALL', name: 'Hallway' }, { id: 'LAB', name: 'Laboratory' }])
    const review = ref<object | null>(null)
    return () => h('main', { class: 'min-h-screen bg-slate-950 p-8 text-white space-y-4' }, [
      h(ItemsTab, {
        editorObjects: [], editorSwitches: [], editorContainers: [], editorTextLogs: [],
        isBatchGenerating: {}, isQuickGenerating: {}, activeMenuId: null, ruleEnforcementMode: 'STRICT',
        visualsCacheVersion: 1, editorScenes: scenes.value,
        onAddItem: (id: string | null) => { initialScene.value = id; open.value = true },
      }),
      open.value ? h(ItemCreateDialog, {
        adventureId: 'item-fixture', scenes: scenes.value, initialSceneId: initialScene.value,
        onClose: () => { open.value = false },
        onDraft: (draft: ItemDraft, sceneId: string) => {
          review.value = { item_type: draft.item_type, sceneId, ...itemDraftFields(draft) }
          open.value = false
        },
      }) : null,
      h('button', { id: 'remove-scenes', onClick: () => { scenes.value = [] } }, 'Remove scenes'),
      h('pre', { id: 'review' }, JSON.stringify(review.value)),
    ])
  },
}).mount('#app')
