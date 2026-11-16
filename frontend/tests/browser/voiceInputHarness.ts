import { createApp, defineComponent, h, nextTick, ref } from 'vue'
import { createMemoryHistory, createRouter, RouterView, useRoute } from 'vue-router'
import '../../src/assets/main.css'
import ImmersiveGameView from '../../src/components/game/ImmersiveGameView.vue'
import { configState } from '../../src/store/config'

const sends = ref<{ session: string; text: string }[]>([]), visible = ref(true), busy = ref(false)
let routeInstances = 0
const Game = defineComponent({ setup() {
  const route = useRoute()
  routeInstances++
  return () => visible.value ? h(ImmersiveGameView, {
    gameId: String(route.params.id), status: busy.value ? 'loading' : 'connected', mode: 'rpg',
    messages: [{ id: 'reply', role: 'assistant', content: 'The fictional archive is quiet.', timestamp: new Date() }],
    sheet: { name: 'Alex', hp: 10, max_hp: 10, mana: 5, stamina: 5, inventory: [], equipment: {}, rule_enforcement_mode: 'rpg' },
    entities: [], inventory: [], items: [], sceneExits: [], sceneSwitches: [], npcMetadata: {},
    currentSceneName: 'Fictional archive', adventureTitle: 'Voice lifecycle example',
    onSend(text: string) { sends.value.push({ session: String(route.params.id), text }) },
  }) : null
} })
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/game/:id', component: Game }] })
await router.push('/game/A')
configState.isBackendReachable = true
Object.assign(window, { voiceFixture: {
  sends,
  get routeInstances() { return routeInstances },
  get health() { return { reachable: configState.isBackendReachable, error: configState.lastErrorMessage } },
  async switchSession(id: string) { await router.push(`/game/${id}`); await nextTick() },
  async leave() { visible.value = false; await nextTick() },
  async show() { visible.value = true; await nextTick() },
  async setBusy(value: boolean) { busy.value = value; await nextTick() },
} })
createApp({ render: () => h('main', { class: 'h-dvh flex flex-col bg-slate-950 text-slate-100' }, [
  h('p', { class: 'shrink-0 p-2 text-xs' }, 'Fictional voice lifecycle fixture'),
  h('div', { class: 'flex-1 min-h-0' }, h(RouterView)),
  h('output', { 'aria-label': 'Sent actions', class: 'shrink-0 p-2 text-xs' }, JSON.stringify(sends.value)),
]) }).use(router).mount('#app')
