import { createApp, h, ref, type Component } from 'vue'
import { BookOpen } from 'lucide-vue-next'
import '../../src/assets/main.css'
import 'rpg-awesome/css/rpg-awesome.min.css'
import { useAuthoringTheme } from '../../src/composables/useAuthoringTheme'
import { authState } from '../../src/store/auth'
import { adventure, entityForm, finding, installAuthoringWindowApi, npc, objects, proposals, references, scenes } from './authoringWindowFixtures'
import AdventureCatalogSelector from '../../src/components/create-adventure/AdventureCatalogSelector.vue'
import AdventureClothingSettings from '../../src/components/create-adventure/AdventureClothingSettings.vue'
import SequencesSection from '../../src/components/editor/SequencesSection.vue'
import ItemCreateDialog from '../../src/components/editor/ItemCreateDialog.vue'
import NpcCreateDialog from '../../src/components/editor/NpcCreateDialog.vue'
import MoveItemToSceneModal from '../../src/components/editor/MoveItemToSceneModal.vue'
import QuestTab from '../../src/components/editor/QuestTab.vue'
import AwardsTab from '../../src/components/editor/AwardsTab.vue'
import ScriptsTab from '../../src/components/editor/ScriptsTab.vue'
import ValidationTab from '../../src/components/editor/ValidationTab.vue'
import EditEntityModal from '../../src/components/editor/EditEntityModal.vue'
import ItemTypeSelectorModal from '../../src/components/editor/ItemTypeSelectorModal.vue'
import AddExistingItemModal from '../../src/components/editor/AddExistingItemModal.vue'
import ManualVisionModal from '../../src/components/editor/ManualVisionModal.vue'
import DataDebugModal from '../../src/components/editor/DataDebugModal.vue'
import EditExitModal from '../../src/components/editor/EditExitModal.vue'
import NpcCombatModal from '../../src/components/editor/NpcCombatModal.vue'
import AIFixSuggestionsModal from '../../src/components/editor/AIFixSuggestionsModal.vue'
import NpcPersonalityDetails from '../../src/components/editor/NpcPersonalityDetails.vue'
import ConcordiaSettingsModal from '../../src/components/living-world/ConcordiaSettingsModal.vue'
import ClothingDetailSettings from '../../src/components/editor/ClothingDetailSettings.vue'
import ProtagonistImportConfirmDialog from '../../src/components/editor/ProtagonistImportConfirmDialog.vue'

const fixture = installAuthoringWindowApi()
Object.assign(window, { authoringWindows: fixture })
Object.assign(authState, { user: { id: 'fictional-author', username: 'Storykeeper', role: 'admin' }, token: 'fictional-preview', isAuthenticated: true, isInitialized: true })
const selected = new URLSearchParams(location.search).get('window') || 'catalog'
const common = { adventure, editorScenes: scenes, editorObjects: objects, editorNpcs: [npc], referenceOptions: references }
const windows: Record<string, { component: Component; props: Record<string, unknown> }> = {
  catalog: { component: AdventureCatalogSelector, props: { title: 'Visual style', subtitle: 'Choose a style', icon: BookOpen, items: [{ id: 'watercolour', name: 'Watercolour', description: 'Soft painted light.' }, { id: 'ink', name: 'Ink', description: 'Clear lines and shadows.' }], selectedId: 'watercolour', accentColorClass: 'text-cyan-400' } },
  'create-options': { component: AdventureClothingSettings, props: { clothingValue: false, nsfwEnabled: false, nsfwLevel: 'soft' } },
  sequences: { component: SequencesSection, props: common },
  'create-item': { component: ItemCreateDialog, props: { adventureId: 'coast', scenes, initialSceneId: 'ARCHIVE' } },
  'create-npc': { component: NpcCreateDialog, props: { adventureId: 'coast', scenes, initialSceneId: 'ARCHIVE', innerClothingEnabled: false } },
  move: { component: MoveItemToSceneModal, props: { show: true, itemName: 'Sealed letter', itemId: 'LETTER', currentSceneId: 'ARCHIVE', sceneOptions: scenes, isSaving: false } },
  quests: { component: QuestTab, props: common },
  awards: { component: AwardsTab, props: common },
  scripts: { component: ScriptsTab, props: common },
  validation: { component: ValidationTab, props: { templateId: 'coast', adventureTitle: adventure.title } },
  'edit-npc': { component: EditEntityModal, props: { show: true, context: { type: 'npc', id: 'MIRA' }, initialForm: entityForm, ruleEnforcementMode: 'rpg', isSaving: false, adventureId: 'coast', npcData: npc, referenceOptions: references } },
  'item-type': { component: ItemTypeSelectorModal, props: { show: true, mode: 'change', currentItemName: 'Sealed letter', currentItemType: 'READABLE', sceneLabel: 'The Old Archive' } },
  existing: { component: AddExistingItemModal, props: { show: true, kind: 'items', sceneLabel: 'Harbour', items: objects, visualsCacheVersion: 0 } },
  vision: { component: ManualVisionModal, props: { show: true, adventureId: 'coast', selectedVisual: { kind: 'scene', id: 'ARCHIVE', label: 'The Old Archive', description: 'Shelves of coastal charts.', hint: '' }, visualPrompt: 'Quiet coastal archive after the rain.', isSuggestingPrompt: false, isRegenerating: false, useAdvancedModel: false, useCurrentImage: false, uploadLimits: { scene: { maxBytes: 10485760 } }, formatBytes: (bytes: number) => `${bytes} bytes`, fixNewlines: (text: string) => text } },
  debug: { component: DataDebugModal, props: { show: true, adventure, debugData: { scenes, objects, npcs: [npc] } } },
  exit: { component: EditExitModal, props: { show: true, isCreateMode: false, fromSceneId: 'ARCHIVE', activeEditExitId: 'COASTAL_PATH', initialForm: { from_scene_id: 'ARCHIVE', to_scene_id: 'HARBOUR', label: 'Coastal path', exit_type: 'bidirectional', lock_description: '' }, sceneReferenceOptions: scenes, referenceOptions: references, isSavingText: false } },
  combat: { component: NpcCombatModal, props: { open: true, adventureId: 'coast', npc, referenceOptions: references } },
  suggestions: { component: AIFixSuggestionsModal, props: { open: true, proposals, loading: false, applying: false, selectedIndex: 0, findingCode: finding.code, findingMessage: finding.message, findingLocation: finding.location, hasBackupConfirmed: false } },
  personality: { component: NpcPersonalityDetails, props: { modelValue: {}, adventureId: 'coast', name: npc.name, description: npc.description, goal: npc.goal, character: npc.character } },
  concordia: { component: ConcordiaSettingsModal, props: { modelValue: { living_world_enabled: true, deliberation_enabled: true, decision_engine: 'concordia' }, existing: false } },
  'editor-options': { component: ClothingDetailSettings, props: { modelValue: false, savedValue: false, isSaving: false, nsfwEnabled: false, nsfwSavedEnabled: false, nsfwLevel: 'soft', nsfwSavedLevel: 'soft' } },
  'protagonist-import': { component: ProtagonistImportConfirmDialog, props: {} },
}
createApp({ setup() {
  useAuthoringTheme()
  const open = ref(true)
  const current = windows[selected]
  const close = () => { fixture.events.push('close'); open.value = false }
  return () => h('main', { class: 'workspace-view authoring-view min-h-dvh p-4 text-slate-200' }, [
    h('p', { class: 'mb-4 text-sm text-slate-400' }, 'Window validation · fictional data'),
    current && open.value ? h(current.component, { ...current.props, onClose: close, onCancel: close, onSave: () => fixture.events.push('save'), onApply: close, onSelect: () => fixture.events.push('select') }) : h('p', 'Closed'),
  ])
} }).mount('#app')
