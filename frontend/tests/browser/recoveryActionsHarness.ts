import { createApp, h, ref } from 'vue'
import '../../src/assets/main.css'
import AIFixSuggestionsModal from '../../src/components/editor/AIFixSuggestionsModal.vue'
import DebugItemRepair from '../../src/components/game/DebugItemRepair.vue'
import ResponseActions from '../../src/components/game/ResponseActions.vue'
import { useGameSocket } from '../../src/composables/useGameSocket'

const socket = useGameSocket()
socket.status.value = 'connected'
socket.messages.value = [
  { id: 'action', role: 'user', content: 'Open the window.', timestamp: new Date() },
  { id: 'answer', role: 'assistant', content: 'The window opens.', timestamp: new Date() },
]

createApp({
  setup() {
    const open = ref(true), retries = ref(0), disabled = ref(false)
    return () => h('main', { class: 'min-h-screen bg-slate-950 p-8 text-white' }, [
      h(AIFixSuggestionsModal, {
        open: open.value, proposals: [], loading: false, applying: false,
        selectedIndex: -1, findingCode: 'missing_outfit', findingMessage: 'Missing outfit',
        hasBackupConfirmed: false, onRetry: () => { retries.value++ },
        onClose: () => { open.value = false },
      }),
      h('output', { id: 'retries' }, String(retries.value)),
      h(ResponseActions, { gameId: 'session', disabled: disabled.value }),
      h('button', { onClick: () => { disabled.value = !disabled.value } }, 'Toggle evaluation lock'),
      h(DebugItemRepair, { sessionId: 'session', itemId: 'COAT', name: 'Coat' }),
    ])
  },
}).mount('#app')
