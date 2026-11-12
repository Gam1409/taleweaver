import { createApp, h, nextTick, ref } from 'vue'
import '../../src/assets/main.css'
import ImmersiveGameView from '../../src/components/game/ImmersiveGameView.vue'
import MapModal from '../../src/components/game/MapModal.vue'
import CharacterSheetModal from '../../src/components/game/CharacterSheetModal.vue'
import { useGameSocket } from '../../src/composables/useGameSocket'
import type { ChatMessage } from '../../src/types'

// Production components with fictional data; no session or model API is called.
const events: string[] = []
const requests: string[] = []
let replayFailure = false
const originalFetch = window.fetch.bind(window)
window.fetch = async (input, options) => {
  const path = typeof input === 'string' ? input : input instanceof URL ? input.pathname : input.url
  if (!path.includes('/api/')) return originalFetch(input, options)
  requests.push(path)
  if (path.endsWith('/chat/replay')) return replayFailure ? Response.json({ detail: 'Snapshot check unavailable' }, { status: 503 }) : Response.json({ available: true, message_id: 'answer' })
  if (path.endsWith('/versions')) return Response.json({ versions: [{ id: 'original', content: 'The archive is quiet.', origin: 'original' }], current_revision_id: 'original' })
  if (path.endsWith('/chat/regenerate')) return Response.json({ id: 'answer', role: 'assistant', content: 'A soft knock comes from the neighbouring room.\n\nMira: "The letter is waiting on the table."', timestamp: new Date(), narration_correction_applied: true })
  return Response.json({ items: [], settings: { enabled: false }, available: false })
}
const socket = useGameSocket()
socket.status.value = 'connected'
socket.sheet.value = { name: 'Alex', role: 'Researcher', debug_mode: true, rule_enforcement_mode: 'rpg', hp: 100, max_hp: 100, mana: 50, max_mana: 50, stamina: 50, max_stamina: 50, inventory: [{ id: 'NOTEBOOK', name: 'Notebook', item_type: 'READABLE', description: 'Notes from the coast.' }], equipment: {}, strength: 10, dexterity: 12, intelligence: 15, wisdom: 14, charisma: 12, armor_class: 10 } as any
socket.entities.value = [{ id: 'MIRA', entity_type: 'NPC', name: 'Mira', role: 'Archivist', hp: 100, max_hp: 100 }, { id: 'OWEN', entity_type: 'NPC', name: 'Owen', role: 'Harbour keeper', hp: 100, max_hp: 100 }]
socket.messages.value = [
  { id: 'action', role: 'user', content: 'I open the door of the old archive and look around.', timestamp: new Date() },
  { id: 'answer', role: 'assistant', content: 'The old archive smells of paper and rain. Evening light fades beyond the window.\n\nMira: "You found the letter. I was hoping you would come."\n\nOwen: "The lighthouse mark is on the map, too."', timestamp: new Date() },
] as ChatMessage[]
socket.sendMessage = async () => { events.push('replay') }
socket.deleteMessage = async () => { events.push('undo') }
const mapData = {
  current_scene_id: 'ARCHIVE',
  nodes: { HARBOUR: { id: 'HARBOUR', label: 'Harbour' }, ARCHIVE: { id: 'ARCHIVE', label: 'Old Archive' }, LIGHTHOUSE: { id: 'LIGHTHOUSE', label: 'Lighthouse' } },
  edges: [{ from: 'HARBOUR', to: 'ARCHIVE', exit_type: 'bidirectional' }, { from: 'ARCHIVE', to: 'LIGHTHOUSE', exit_type: 'one_way' }],
}

createApp({
  setup() {
    const mapOpen = ref(false), sheetOpen = ref(false), mode = ref<'rpg' | 'vn'>('rpg')
    const detail = ref<HTMLDialogElement>(), detailTitle = ref('')
    const suggestions = ref(['Examine the seal on the letter.', 'Study the map of the coast.', 'Ask Mira about the lighthouse.'])
    function record(name: string) { events.push(name) }
    async function show(name: string) {
      record(name)
      detailTitle.value = name
      await nextTick()
      detail.value?.showModal()
    }
    Object.assign(window, { groupedActionsFixture: {
      events, requests,
      setReplayFailure(value: boolean) { replayFailure = value },
      refreshReplayCheck() { socket.status.value = socket.status.value === 'connected' ? 'completed' : 'connected' },
      setMode(value: 'rpg' | 'vn') { mode.value = value },
      setBusy(value: boolean) { socket.status.value = value ? 'loading' : 'connected' },
      setDebug(value: boolean) { socket.sheet.value = { ...socket.sheet.value!, debug_mode: value } },
    } })
    return () => h('main', { class: 'h-dvh flex flex-col bg-slate-950 text-slate-100' }, [
      h('div', { class: 'h-7 shrink-0 flex items-center justify-between gap-3 border-b border-slate-800 px-4 text-[10px] text-slate-400' }, [
        h('span', 'Current interface · grouped actions · fictional preview'),
        h('a', { href: '/layouts.html', class: 'text-amber-300 hover:underline' }, 'Design examples'),
      ]),
      h('div', { class: 'flex-1 min-h-0' }, h(ImmersiveGameView, {
        gameId: 'grouping-preview', messages: socket.messages.value, status: socket.status.value,
        sheet: socket.sheet.value, entities: socket.entities.value, npcMetadata: {}, inventory: socket.sheet.value?.inventory || [],
        sceneExits: [], sceneSwitches: [], items: [], mode: mode.value, currentSceneName: 'The Old Archive',
        currentSceneImage: new URL(`${import.meta.env.BASE_URL}assets/background/background5.jpg`, window.location.origin).href,
        gameTime: { dateShort: 'Day 3', time: '18:42' }, exp: 120, adventureTitle: 'Letters from the Coast',
        trackedQuest: { title: 'A letter without an address' }, worldMemories: [{ id: 'seal' }], promptSuggestions: suggestions.value,
        onOpenMap: () => { record('World map'); mapOpen.value = true },
        onOpenSheet: () => { record('Hero & inventory'); sheetOpen.value = true },
        onOpenQuests: () => show('Quests'), onOpenChronicles: () => show('Chronicles'),
        onOpenMemories: () => show('World memories'), onOpenCharacters: () => show('Characters'),
        onOpenDebug: () => show('Debug inspector'), onOpenWalkthrough: () => show('Adventure hints'),
        onOpenSettings: () => show('Session settings'),
        onRefreshSuggestions: () => { suggestions.value = ['Check the date on the letter.', 'Compare the two lighthouse marks.'] },
        onSend: text => { record(`send:${text}`) },
      })),
      h(MapModal, { open: mapOpen.value, mapData, nodes: mapData.nodes, onClose: () => { mapOpen.value = false } }),
      h(CharacterSheetModal, { open: sheetOpen.value, sheet: socket.sheet.value, onClose: () => { sheetOpen.value = false } }),
      h('dialog', { ref: detail, class: 'm-auto w-80 max-w-[90vw] rounded-2xl border border-slate-700 bg-slate-900 p-6 text-slate-100 backdrop:bg-black/70' }, [
        h('h2', { class: 'text-lg font-bold mb-3' }, detailTitle.value),
        h('p', { class: 'text-sm text-slate-400 mb-5' }, 'This action opens the existing session panel. Preview data is fictional.'),
        h('button', { onClick: () => detail.value?.close(), class: 'rounded-lg border border-slate-600 px-4 py-2' }, 'Close preview panel'),
      ]),
    ])
  },
}).mount('#app')
