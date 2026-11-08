import { createApp, h, ref } from 'vue'
import '../../src/assets/main.css'
import InhabitantsTab from '../../src/components/editor/InhabitantsTab.vue'
import NpcCreateDialog from '../../src/components/editor/NpcCreateDialog.vue'

createApp({
  setup() {
    const open = ref(false), created = ref('')
    const scenes = ref([{ id: 'HALL', name: 'Hallway' }, { id: 'LAB', name: 'Laboratory' }])
    return () => h('main', { class: 'min-h-screen bg-slate-950 p-8 text-white' }, [
      h(InhabitantsTab, {
        form: {}, adventure: {}, debugData: {}, editorNpcs: [], isBatchGenerating: {},
        isQuickGenerating: {}, activeMenuId: null, ruleEnforcementMode: 'vn', visualsCacheVersion: 0,
        onNewNpc: () => { open.value = true },
      }),
      open.value ? h(NpcCreateDialog, {
        adventureId: 'npc-fixture', scenes: scenes.value, initialSceneId: 'LAB', innerClothingEnabled: true,
        onClose: () => { open.value = false },
        onCreated: (id: string) => { created.value = id; open.value = false },
      }) : null,
      h('button', { id: 'remove-scenes', onClick: () => { scenes.value = [] } }, 'Remove scenes'),
      h('p', { id: 'created' }, created.value),
    ])
  },
}).mount('#app')
