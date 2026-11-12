import { createApp, h, ref } from 'vue'
import '../../src/assets/main.css'
import GameHoverTooltip from '../../src/components/game/GameHoverTooltip.vue'

createApp({
  setup() {
    const detail = ref('Half full of water.')
    return () => h('main', { class: 'min-h-screen bg-slate-950 p-4 text-white' }, [
      h('button', { onClick: () => { detail.value = 'Empty. <script>not executable</script>' } }, 'Empty the flask'),
      h(GameHoverTooltip, {
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
