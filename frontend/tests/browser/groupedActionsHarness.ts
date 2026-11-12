import { createApp, h, nextTick, ref, watch } from 'vue'
import '../../src/assets/main.css'
import 'rpg-awesome/css/rpg-awesome.min.css'
import ImmersiveHeader from '../../src/components/game/immersive/ImmersiveHeader.vue'
import { configState } from '../../src/store/config'
import { audioService } from '../../src/services/audioService'
import { updateNpcBehaviorStatus } from '../../src/composables/useNpcBehaviorStatus'
import ImmersiveGameView from '../../src/components/game/ImmersiveGameView.vue'
import MapModal from '../../src/components/game/MapModal.vue'
import CharacterSheetModal from '../../src/components/game/CharacterSheetModal.vue'
import { useGameSocket } from '../../src/composables/useGameSocket'
import SessionSettingsModal from '../../src/components/game/SessionSettingsModal.vue'
import { createSessionSettingsFixture } from './sessionSettingsFixture'
import SessionNpcModals from '../../src/components/game/SessionNpcModals.vue'
import { createCharacterPanelFixture } from './characterPanelFixture'
import type { PortraitTarget } from '../../src/composables/useSessionPortrait'
import type { ChatMessage } from '../../src/types'

// Production components with fictional data; no session or model API is called.
const events: string[] = []
const requests: string[] = []
let replayFailure = false
const sessionSettingsFixture = createSessionSettingsFixture()
const characterPanelFixture = createCharacterPanelFixture()
const originalFetch = window.fetch.bind(window)
window.fetch = async (input, options) => {
  const path = typeof input === 'string' ? input : input instanceof URL ? input.pathname : input.url
  if (!path.includes('/api/')) return originalFetch(input, options)
  requests.push(path)
  const characterReply = characterPanelFixture.respond(path, options?.method || 'GET', typeof options?.body === 'string' ? JSON.parse(options.body) : undefined)
  if (characterReply) return characterReply
  const settingsReply = sessionSettingsFixture.respond(path, options?.method || 'GET', typeof options?.body === 'string' ? JSON.parse(options.body) : undefined)
  if (settingsReply) return settingsReply
  if (path.includes('/illustrations?')) return Response.json({ available: false, reason: 'Image generation is not connected in this preview.', image_url: null })
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
  { id: 'notice', role: 'system', content: 'The archive door is open.', timestamp: new Date() },
  { id: 'answer', role: 'assistant', content: 'The old archive smells of paper and rain. Evening light fades beyond the window.\n\nMira: "You found the letter. I was hoping you would come."\n\nOwen: "The lighthouse mark is on the map, too."', timestamp: new Date() },
] as ChatMessage[]
socket.setLanguage = async value => { socket.language.value = value; events.push(`language:${value}`); return true }
socket.sendMessage = async () => { events.push('replay') }
socket.deleteMessage = async () => { events.push('undo') }
const mapData = {
  current_scene_id: 'ARCHIVE',
  nodes: { HARBOUR: { id: 'HARBOUR', label: 'Harbour' }, ARCHIVE: { id: 'ARCHIVE', label: 'Old Archive' }, LIGHTHOUSE: { id: 'LIGHTHOUSE', label: 'Lighthouse' } },
  edges: [{ from: 'HARBOUR', to: 'ARCHIVE', exit_type: 'bidirectional' }, { from: 'ARCHIVE', to: 'LIGHTHOUSE', exit_type: 'one_way' }],
}

createApp({
  setup() {
    const params = new URLSearchParams(window.location.search)
    const mapOpen = ref(false), sheetOpen = ref(false), settingsOpen = ref(params.get('panel') === 'settings'), mode = ref<'rpg' | 'vn'>(params.get('mode') === 'vn' ? 'vn' : 'rpg')
    watch(mode, value => { socket.sheet.value = { ...socket.sheet.value!, rule_enforcement_mode: value } }, { immediate: true })
    function modeHref(value: 'rpg' | 'vn') {
      const query = new URLSearchParams(params)
      query.set('mode', value)
      return '?' + query.toString()
    }
    const detail = ref<HTMLDialogElement>(), detailTitle = ref('')
    const charactersOpen = ref(false), portrait = ref<PortraitTarget | null>(params.get('panel') === 'character' ? { id: 'MIRA', name: 'Mira' } : null), portraitError = ref('')
    function openCharacter(npc: PortraitTarget) { portraitError.value = ''; portrait.value = npc }
    const headerOnly = new URLSearchParams(window.location.search).has('header-only')
    const header = ref<any>({ sceneName: 'The Old Archive', adventureTitle: 'Letters from the Coast', gameTime: { dateShort: 'Day 3', time: '18:42' }, exp: 120, trackedQuest: { title: 'A letter without an address' } })
    const suggestions = ref(['Examine the seal on the letter.', 'Study the map of the coast.', 'Ask Mira about the lighthouse.'])
    const memory = ref({ turns: 10, enableCompression: true, autoSpeakNarration: true, autoSpeakDialogues: true })
    function record(name: string) { events.push(name) }
    async function show(name: string) {
      record(name)
      detailTitle.value = name
      await nextTick()
      detail.value?.showModal()
    }
    Object.assign(window, { groupedActionsFixture: {
      events, requests,
      settingsWrites: sessionSettingsFixture.writes,
      failSettingsSave(endpoint: string) { sessionSettingsFixture.failSave(endpoint) },
      setHeader(value: Record<string, unknown>) { header.value = { ...header.value, ...value } },
      setSpeech(enabled: boolean, playing = false, auto = false) { configState.isTtsEnabled = enabled; audioService.isPlaying.value = playing; audioService.autoSpeechEnabled.value = auto },
      setBehavior(value: unknown) { updateNpcBehaviorStatus('grouping-preview', value) },
      setReplayFailure(value: boolean) { replayFailure = value },
      refreshReplayCheck() { socket.status.value = socket.status.value === 'connected' ? 'completed' : 'connected' },
      setMode(value: 'rpg' | 'vn') { mode.value = value },
      setBusy(value: boolean) { socket.status.value = value ? 'loading' : 'connected' },
      setDebug(value: boolean) { socket.sheet.value = { ...socket.sheet.value!, debug_mode: value } },
    } })
    return () => h('main', { class: 'h-dvh flex flex-col bg-slate-950 text-slate-100' }, [
      h('div', { class: 'min-h-8 shrink-0 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-slate-800 px-3 py-1 text-[10px] text-slate-400' }, [
        h('span', { class: 'hidden sm:inline' }, 'Fictional interface preview'),
        h('nav', { 'aria-label': 'Preview mode', class: 'flex items-center gap-1' }, (['rpg', 'vn'] as const).map(value =>
          h('a', { href: modeHref(value), 'aria-current': mode.value === value ? 'page' : undefined, class: 'rounded border px-2 py-0.5 ' + (mode.value === value ? 'border-amber-400/30 bg-amber-400/10 text-amber-200' : 'border-transparent hover:text-slate-100') }, value === 'vn' ? 'Visual mode' : 'RPG')
        )),
        h('a', { href: '/layouts.html', class: 'text-amber-300 hover:underline' }, 'Design examples'),
      ]),
      h('div', { class: 'flex-1 min-h-0' }, headerOnly ? h(ImmersiveHeader, {
        ...header.value, mode: mode.value, debugMode: !!socket.sheet.value?.debug_mode, sessionId: 'grouping-preview',
        onOpenQuests: () => show('Quests'), onOpenChronicles: () => show('Chronicles'), onOpenSettings: () => { record('Session settings'); settingsOpen.value = true },
        onOpenDebug: () => show('Debug inspector'), onExitSession: () => show('Exit session'), onToggleMobileInteract: () => show('Interact'),
      }) : h(ImmersiveGameView, {
        gameId: 'grouping-preview', messages: socket.messages.value, status: socket.status.value,
        sheet: socket.sheet.value, entities: socket.entities.value, npcMetadata: {}, inventory: socket.sheet.value?.inventory || [],
        sceneExits: [{ id: 'HARBOUR_PATH', label: 'Harbour path', target_scene_id: 'HARBOUR', target_scene_name: 'Harbour', is_locked: false }, { id: 'TOWER_STAIR', label: 'Tower stair', target_scene_id: 'LIGHTHOUSE', target_scene_name: 'Lighthouse', is_locked: true }],
        sceneSwitches: [{ id: 'READING_LAMP', name: 'Reading lamp', switch_state: 'off' }],
        items: [{ id: 'LETTER', name: 'Sealed letter', item_type: 'READABLE', is_portable: true, description: 'A letter with a lighthouse seal.' }, { id: 'COAST_MAP', name: 'Coastal chart', item_type: 'READABLE', is_portable: false, description: 'A chart pinned to the archive table.' }], mode: mode.value, currentSceneName: header.value.sceneName,
        currentSceneImage: new URL(`${import.meta.env.BASE_URL}assets/background/background5.jpg`, window.location.origin).href,
        gameTime: header.value.gameTime, exp: header.value.exp, adventureTitle: header.value.adventureTitle,
        trackedQuest: header.value.trackedQuest, worldMemories: [{ id: 'seal' }], promptSuggestions: suggestions.value,
        onOpenMap: () => { record('World map'); mapOpen.value = true },
        onOpenSheet: () => { record('Hero & inventory'); sheetOpen.value = true },
        onOpenQuests: () => show('Quests'), onOpenChronicles: () => show('Chronicles'),
        onOpenMemories: () => show('World memories'), onOpenCharacters: () => { record('Characters'); charactersOpen.value = true },
        onNpcPortrait: openCharacter,
        onOpenDebug: () => show('Debug inspector'), onOpenWalkthrough: () => show('Adventure hints'),
        onExitSession: () => show('Exit session'),
        onOpenSettings: () => { record('Session settings'); settingsOpen.value = true },
        onRefreshSuggestions: () => { suggestions.value = ['Check the date on the letter.', 'Compare the two lighthouse marks.'] },
        onSend: text => { record(`send:${text}`) },
        onTraverseExit: exit => record(`passage:${exit.id}`),
        onSwitchFlip: item => record(`switch:${item.id}`),
        onTakeDirect: item => record(`take:${item.id}`),
        onItemClick: item => show(item.name),
      })),
      settingsOpen.value ? h(SessionSettingsModal, { sessionId: 'grouping-preview', mode: mode.value, initialTurns: memory.value.turns, initialCompression: memory.value.enableCompression, initialAutoSpeakNarration: memory.value.autoSpeakNarration, initialAutoSpeakDialogues: memory.value.autoSpeakDialogues, onClose: () => { settingsOpen.value = false }, onSave: value => { memory.value = value; record('settings:save:' + JSON.stringify(value)); settingsOpen.value = false } }) : null,
      h(MapModal, { open: mapOpen.value, mapData, nodes: mapData.nodes, onClose: () => { mapOpen.value = false } }),
      h(CharacterSheetModal, { open: sheetOpen.value, sheet: socket.sheet.value, onClose: () => { sheetOpen.value = false } }),
      h(SessionNpcModals, { sessionId: 'grouping-preview', refined: !params.has('original-card'), directoryOpen: charactersOpen.value, npc: portrait.value, busy: false, error: portraitError.value, updated: false, onCloseDirectory: () => { charactersOpen.value = false }, onSelect: openCharacter, onCloseCard: () => { portrait.value = null }, onGenerate: () => { portraitError.value = 'Portrait generation is not connected in this preview.' } }),
      h('dialog', { ref: detail, class: 'm-auto w-80 max-w-[90vw] rounded-2xl border border-slate-700 bg-slate-900 p-6 text-slate-100 backdrop:bg-black/70' }, [
        h('h2', { class: 'text-lg font-bold mb-3' }, detailTitle.value),
        h('p', { class: 'text-sm text-slate-400 mb-5' }, 'This action opens the existing session panel. Preview data is fictional.'),
        h('button', { onClick: () => detail.value?.close(), class: 'rounded-lg border border-slate-600 px-4 py-2' }, 'Close preview panel'),
      ]),
    ])
  },
}).mount('#app')
