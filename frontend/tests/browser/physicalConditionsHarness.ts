import { createApp, h, ref } from 'vue'
import '../../src/assets/main.css'
import DebugModal from '../../src/components/game/DebugModal.vue'

const source = { kind: 'narration', message_id: 'reply1', quote: 'Rin bandaged her neck wound.' }
const condition = { id: 'C1', target_id: 'RIN', kind: 'injury', part: 'neck', detail: 'A bandaged neck wound.', status: 'treated', visibility: 'public', origin: source, latest: source }
createApp({
  setup() {
    const ledger = ref({ revision: 1, conditions: { C1: condition } as Record<string, typeof condition>, subjects: [{ id: '__player__', name: 'Hero' }, { id: 'RIN', name: 'Rin' }], archived_resolved: 0, archived_events: 0, last_check: { status: 'complete' } })
    const command = ref('')
    async function executeCommand(value: string) {
      command.value = value
      const proposal = JSON.parse(value.slice('/debug condition '.length))
      const existing = ledger.value.conditions[proposal.condition_id]
      const id = proposal.condition_id || 'C2'
      ledger.value = { ...ledger.value, revision: ledger.value.revision + 1, conditions: { ...ledger.value.conditions, [id]: { ...condition, ...existing, ...proposal, id, status: proposal.operation === 'heal' ? 'resolved' : existing?.status || 'active', latest: { kind: 'manual', message_id: '', quote: 'Explicit manual debug correction.' } } } }
    }
    return () => h('main', { class: 'min-h-screen bg-slate-950' }, [
      h(DebugModal, { open: true, data: { fullWorld: { session: { id: 'fixture', current_scene_id: 'LAB' }, physical_conditions: ledger.value } }, executeCommand }),
      h('output', { id: 'last-command', hidden: true }, command.value),
    ])
  },
}).mount('#app')
