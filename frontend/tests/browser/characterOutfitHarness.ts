import { createApp, h, ref } from 'vue'
import '../../src/assets/main.css'
import EditEntityModal from '../../src/components/editor/EditEntityModal.vue'

createApp({
  setup() {
    const show = ref(true), saved = ref('')
    const form = {
      name: 'Rin', teaser: '', description: 'A reserved doctor with dark hair and grey eyes.',
      goal: 'Identify contamination.', character: 'Independent and careful.', gender: 'female', age_years: 32,
      hp: 30, stamina: 20, mana: 0, is_killable: true, item_type: 'DEFAULT', is_portable: true,
      locked: false, code_to_unlock: '', item_to_unlock: '', inventory_input: ['COAT', 'BRA', 'KEY'],
      text_log_content: '', text_log_format: 'DOCUMENT', entity_id: 'RIN', wearable_slots_input: [],
      combination_ingredients_input: [], reveal_rule: '', is_hidden: false, spatial_position: '', reveals_item_id: '',
      switch_states_json: '[]', switch_initial_state: '', switch_transitions_json: '[]', effects_hp: 0,
      effects_stamina: 0, effects_mana: 0, stat_modifier_strength: 0,
    }
    return () => h('main', { class: 'min-h-screen bg-slate-950 p-8 text-white' }, [
      h('button', { onClick: () => { show.value = true } }, 'Edit character'),
      h(EditEntityModal, {
        show: show.value, context: { type: 'npc', id: 'RIN' }, initialForm: form,
        referenceOptions: [{ id: 'RIN', name: 'Rin', type: 'NPC' }, { id: 'COAT', name: 'White coat', type: 'OBJECT' }, { id: 'BRA', name: 'Red bra', type: 'OBJECT' }, { id: 'KEY', name: 'Laboratory key', type: 'OBJECT' }],
        ruleEnforcementMode: 'vn', isSaving: false, adventureId: 'outfit-fixture', isCreateEntityMode: false,
        onClose: () => { show.value = false }, onSave: (value: object) => { saved.value = JSON.stringify(value); show.value = false },
      }),
      h('pre', { id: 'saved-outfit' }, saved.value),
    ])
  },
}).mount('#app')
