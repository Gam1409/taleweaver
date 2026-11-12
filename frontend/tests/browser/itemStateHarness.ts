import { createApp, h, ref } from 'vue'
import '../../src/assets/main.css'
import GameHoverTooltip from '../../src/components/game/GameHoverTooltip.vue'
import NpcCurrentState from '../../src/components/game/NpcCurrentState.vue'

createApp({
  setup() {
    const detail = ref('Half full of water.')
    const showNpc = ref(false)
    return () => h('main', { class: 'min-h-screen bg-slate-950 p-4 text-white' }, [
      h('button', { onClick: () => { detail.value = 'Empty. <script>not executable</script>' } }, 'Empty the flask'),
      h('button', { onClick: () => { showNpc.value = true }, class: 'ml-4' }, 'Show NPC equipment'),
      showNpc.value ? h(NpcCurrentState, { state: {
        availability: 'present', game_minute: 50,
        layout: { form: 'humanoid', silhouette: 'neutral' },
        clothing: { status: 'available', detail_limited: false, items: [
          { item_id: 'coat', name: 'Coat', description: '', image_url: null, layer: 1,
            slots: ['Chest'], visible_regions: [], uncovered_regions: [],
            current_state: [{ dimension: 'form', detail: 'The coat is crumpled.' }] },
        ] },
        conditions: { status: 'available', items: [
          { id: 'state1', target_id: 'coat', kind: 'item_state', part: 'form',
            detail: 'The coat is crumpled.', status: 'active', observation: 'recorded', last_changed_minute: 50 },
        ] },
      } }) : h(GameHoverTooltip, {
        hoveredEntity: { id: 'flask', name: 'Flask', entity_type: 'ITEM',
          description: 'An originally full metal flask.',
          current_state: [{ dimension: 'fill_level', detail: detail.value }],
        },
        tooltipStyle: { top: '80px', left: '12px', width: 'min(350px, calc(100vw - 24px))' },
        tooltipImageFailed: false, showsMechanics: false, isConsumableHover: false,
      }),
    ])
  },
}).mount('#app')
