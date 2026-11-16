import { computed, createApp, defineComponent, h, nextTick, ref } from 'vue'
import { createMemoryHistory, createRouter, RouterView, useRoute } from 'vue-router'
import { useGameSocket } from '../../src/composables/useGameSocket'
import { useGameSessionLifecycle } from '../../src/composables/useGameSessionLifecycle'
import { usePlayAgentAutoLoop } from '../../src/composables/usePlayAgent'
import { gameViewService } from '../../src/services/gameViewService'
import { notificationService } from '../../src/services/notificationService'
import '../../src/assets/main.css'

// Deferred fictional replies exercise the production lifecycle without a server.
const settings: { signal?: AbortSignal | null; finish: (error?: boolean) => void }[] = []
const aliases: ((id: string | null) => void)[] = []
const requests: { path: string; method: string }[] = []
const visible = ref(true)
const socket = useGameSocket()
const originalFetch = window.fetch.bind(window)
window.fetch = async (input, options) => {
  const path = String(input), method = options?.method || 'GET'
  if (!path.startsWith('/api/')) return originalFetch(input, options)
  requests.push({ path, method })
  if (path.endsWith('/agent/settings')) return new Promise(resolve => settings.push({ signal: options?.signal,
    finish: error => resolve(error ? Response.json({ detail: 'The old example setting was rejected.' }, { status: 409 }) : Response.json({ agent_active: true, agent_step_by_step: false })) }))
  if (path.includes('/old-template/chat')) return Response.json({ detail: 'Example alias.' }, { status: 404 })
  if (path.includes('/chat')) return Response.json({
    messages: [{ id: 'reply', role: 'assistant', content: 'The fictional archive is quiet.' }], scene_id: 'ARCHIVE',
    sheet: { name: path.includes('/B/') ? 'Example B' : 'Example A', agent_active: false, agent_step_by_step: true }, language: 'English',
  })
  return Response.json({ items: [], settings: {} })
}
gameViewService.fetchGameSettings = async () => null
gameViewService.ensureGameIdForRouteId = async () => new Promise(resolve => aliases.push(resolve))
const Game = defineComponent({ setup() {
  const route = useRoute()
  useGameSessionLifecycle({ routeId: computed(() => String(route.params.id)), status: socket.status, gameSettings: ref({ clock_24h: true }),
    router, connect: socket.connect, disconnect: socket.disconnect, closePanels() {} })
  usePlayAgentAutoLoop()
  return () => h('section', { class: 'space-y-3' }, [
    h('p', { 'aria-label': 'Current session' }, String(route.params.id)),
    h('p', { 'aria-label': 'Connection status' }, socket.status.value),
    h('pre', { 'aria-label': 'Session sheet' }, JSON.stringify(socket.sheet.value)),
    h('button', { onClick: () => { void socket.updateAgentSettings({ active: true, step_by_step: false }) } }, 'Save automatic mode'),
  ])
} })
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/game/:id', component: Game }] })
await router.push('/game/A')
Object.assign(window, { sessionOwnershipFixture: {
  settings, aliases, requests, socket, notifications: notificationService.all,
  get route() { return router.currentRoute.value.path },
  async leave() { visible.value = false; await nextTick() },
} })
createApp({ setup() { return () => h('main', { class: 'min-h-dvh bg-slate-950 text-white p-6 space-y-4' }, [
  h('h1', 'Fictional session ownership fixture'),
  h('nav', { class: 'flex gap-4' }, ['A', 'B', 'old-template'].map(id => h('button', { onClick: () => router.push(`/game/${id}`) }, `Open ${id}`))),
  visible.value ? h(RouterView) : h('p', 'Example closed'),
]) } }).use(router).mount('#app')
