import { createApp, h, ref } from 'vue'
import DebugModal from '../../src/components/game/DebugModal.vue'
import SessionSettingsModal from '../../src/components/game/SessionSettingsModal.vue'
import ValidationTab from '../../src/components/editor/ValidationTab.vue'
import LivingWorldTab from '../../src/components/editor/LivingWorldTab.vue'
import { authState } from '../../src/store/auth'
import '../../src/assets/main.css'

authState.user = { id: 'fixture', username: 'Fixture', role: 'admin' }
const people = ['Dr. Rin Aoyama', 'Miki', 'Professor Tanaka'].map((name, index) => ({
  id: `NPC_${index}`, name, current_scene_id: 'CLINIC', hp: 60, max_hp: 60,
  stamina: 70, mana: 0, is_alive: true, is_in_current_scene: true, current_scene_name: 'Doctor’s office', notes: 'A familiar face with her own goals and concerns.', inventory: [], is_hidden: false, moveable: true,
  wardrobe: { items: index === 0 ? [
    { id: 'COAT', name: 'White laboratory coat', description: 'Crisp white fabric falls in clean folds; neatly stitched cuffs and practical pockets complete the coat’s restrained clinical appearance.', clothing: { category: 'clothing', layer: 3, coverage: ['torso', 'arms'], opaque: true, underwear: false, description: 'Pressed white coat' }, worn: true },
    { id: 'BLOUSE', name: 'Ivory blouse', description: 'A softly draped blouse with a tidy collar and a narrow row of buttons.', clothing: { category: 'clothing', layer: 2, coverage: ['torso', 'arms'], opaque: true, underwear: false, description: 'Ivory blouse' }, worn: true },
    { id: 'SKIRT', name: 'Charcoal pencil skirt', description: 'The charcoal fabric follows a straight, tailored silhouette with a neatly finished hem.', clothing: { category: 'clothing', layer: 2, coverage: ['pelvis', 'legs'], opaque: true, underwear: false, description: 'Charcoal skirt' }, worn: true },
    { id: 'STOCKINGS', name: 'Black seamed stockings', description: 'Fine black stockings with a clean seam running down the back of each leg.', clothing: { category: 'clothing', layer: 1, coverage: ['legs', 'feet'], opaque: false, underwear: false, description: 'Black seamed stockings' }, worn: true },
  ] : [], profile_known: true },
}))
const data = {
  sheet: { name: 'Emiral', session_id: 'fixture', scene_id: 'CLINIC', current_scene: 'Doctor’s office' },
  fullWorld: {
    session: { id: 'fixture', current_scene_id: 'CLINIC', current_scene_name: 'Doctor’s office', in_game_time: 59 },
    npcs: people, items: [{ id: 'COAT', name: 'White laboratory coat', description: 'A carefully pressed white coat.', location_type: 'npc', location_name: 'Dr. Rin Aoyama', item_type: 'WEARABLE' }],
    map: { nodes: { CLINIC: { id: 'CLINIC', label: 'Doctor’s office' } }, edges: [] },
  },
}
createApp({
  setup() {
    const view = ref(new URLSearchParams(location.search).get('view') || 'debug')
    const world = ref(null)
    const personality = ref(null)
    return () => h('div', { class: 'min-h-screen bg-slate-950 p-6 text-slate-200' }, [
      h('nav', { class: 'mb-6 flex flex-wrap gap-4' }, ['debug', 'session', 'adventure', 'validation'].map(value => h('button', { class: 'rounded bg-slate-800 px-4 py-2', onClick: () => { view.value = value } }, value))),
      view.value === 'debug' ? h(DebugModal, { open: true, data, executeCommand: async () => undefined, onClose: () => { view.value = 'adventure' } }) : null,
      view.value === 'session' ? h(SessionSettingsModal, { sessionId: 'fixture', mode: 'vn', onClose: () => { view.value = 'adventure' } }) : null,
      view.value === 'adventure' ? h(LivingWorldTab, { livingWorld: world.value, personality: personality.value, characters: people, isVn: true, busy: false, 'onUpdate:livingWorld': value => { world.value = value }, 'onUpdate:personality': value => { personality.value = value } }) : null,
      // Reproduce the editor's transformed/scrolling ancestor, not an isolated modal.
      view.value === 'validation' ? h('div', { style: 'transform: translateZ(0); max-height: 65vh; overflow: auto' }, h(ValidationTab, { templateId: 'fixture', adventureTitle: 'Fixture' })) : null,
    ])
  },
}).mount('#app')
