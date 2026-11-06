import { createApp, h, ref } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import AdminView from '../../src/views/AdminView.vue'
import ImmersiveInputBar from '../../src/components/game/immersive/ImmersiveInputBar.vue'
import NpcPortraitModal from '../../src/components/game/NpcPortraitModal.vue'
import { authState } from '../../src/store/auth'
import '../../src/assets/main.css'

authState.user = { id: 'fixture', username: 'Fixture', role: 'admin' }
authState.token = 'fixture'
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { render: () => null } }] })
createApp({
  setup() {
    const view = new URLSearchParams(location.search).get('view')
    const sent = ref<string[]>([])
    const closed = ref(false)
    return () => h('main', { class: 'min-h-screen bg-slate-950 text-slate-200' }, [
      view === 'input' ? h('div', { class: 'mx-auto max-w-xl pt-8' }, [
        h(ImmersiveInputBar, { canSendInput: true, onSend: (text: string) => { sent.value.push(text) } }),
        h('pre', { id: 'sent', class: 'whitespace-pre-wrap' }, JSON.stringify(sent.value)),
      ]) : null,
      view === 'npc' && !closed.value ? h(NpcPortraitModal, { sessionId: 'fixture', npc: { id: 'NPC_0', name: 'Dr. Rin Aoyama', description: 'An independent physician.', image_url: null }, busy: false, updated: false, error: '', onClose: () => { closed.value = true } }) : null,
      view === 'admin' ? h(AdminView) : null,
    ])
  },
}).use(router).mount('#app')
