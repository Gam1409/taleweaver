import { createApp, h, ref } from 'vue'
import '../../src/assets/main.css'
import 'rpg-awesome/css/rpg-awesome.min.css'
import ImmersiveGameView from '../../src/components/game/ImmersiveGameView.vue'
import WorldInfoModal from '../../src/components/game/WorldInfoModal.vue'
import { createWorldInfoFixture } from './worldInfoFixture'
const fixture = createWorldInfoFixture(Number(new URLSearchParams(location.search).get('records') || 3))
const originalFetch = window.fetch.bind(window)
window.fetch = async (input, options) => {
  const path = typeof input === 'string' ? input : input instanceof URL ? input.pathname : input.url
  const response = await fixture.respond(path, options)
  if (response) return response
  if (path.includes('/api/')) return Response.json({ items: [], available: false })
  return originalFetch(input, options)
}
createApp({ setup() {
  const open = ref(false), sid = ref('world-info-demo')
  Object.assign(window, { worldInfoFixture: { ...fixture, switchSession(value: string) { sid.value = value } } })
  return () => h('main', { class: 'h-dvh flex flex-col bg-slate-950 text-slate-100 font-ui' }, [
    h('div', { class: 'shrink-0 border-b border-slate-800 px-4 py-1 text-xs text-slate-400' }, 'World Info · fictional interface example'),
    h('div', { class: 'min-h-0 flex-1' }, h(ImmersiveGameView, {
      gameId: sid.value, messages: [{ id: 'narration', role: 'assistant', content: 'The archive is quiet. A lantern glows beside a stack of coastal maps.', timestamp: new Date() }], status: 'connected', mode: 'rpg',
      sheet: { name: 'Alex', hp: 100, max_hp: 100, stamina: 50, mana: 50, inventory: [], equipment: {}, rule_enforcement_mode: 'rpg' }, entities: [], npcMetadata: {}, inventory: [], sceneExits: [], sceneSwitches: [], items: [], currentSceneName: 'The Old Archive', adventureTitle: 'Letters from the Coast', gameTime: { dateShort: 'Day 3', time: '18:42' }, exp: 120,
      currentSceneImage: new URL(`${import.meta.env.BASE_URL}assets/background/background5.jpg`, location.origin).href,
      onOpenWorldInfo: () => { open.value = true },
    })),
    open.value ? h(WorldInfoModal, { sessionId: sid.value, onClose: () => { open.value = false } }) : null,
  ])
} }).mount('#app')
