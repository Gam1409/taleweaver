import { createApp, h, onMounted } from 'vue'
import { createRouter, createMemoryHistory, RouterView } from 'vue-router'
import '../../src/assets/main.css'
import 'rpg-awesome/css/rpg-awesome.min.css'
import GlobalHeader from '../../src/components/GlobalHeader.vue'
import PortalView from '../../src/views/PortalView.vue'
import AdminView from '../../src/views/AdminView.vue'
import { authState } from '../../src/store/auth'
import { configState } from '../../src/store/config'
import { createPortalFixture } from './portalFixture'

const fixture = createPortalFixture()
const params = new URLSearchParams(window.location.search)
const originalFetch = window.fetch.bind(window)
window.fetch = async (input, options) => {
  const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
  const url = new URL(raw, window.location.origin)
  if (!url.pathname.startsWith('/api/')) return originalFetch(input, options)
  const body = options?.body instanceof URLSearchParams ? Object.fromEntries(options.body) : typeof options?.body === 'string' ? JSON.parse(options.body) : undefined
  return fixture.respond(url.pathname.slice(4), options?.method || 'GET', body)
}
const loginPreview = params.get('screen') === 'login'
Object.assign(authState, { user: loginPreview ? null : fixture.user, token: loginPreview ? null : 'fictional-preview', isAuthenticated: !loginPreview, isInitialized: true })
Object.assign(configState, { appVersion: '0.7.1-beta', isLoaded: true, hasLlmConfig: true, hasT2iConfig: true })
Object.assign(window, { portalFixture: fixture })
const chatHref = '/?from=portal'
const ChatPreview = { setup() { onMounted(() => window.location.assign(chatHref)); return () => h('a', { href: chatHref }, 'Open chat preview') } }
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'portal', component: PortalView },
    { path: '/admin', name: 'admin', component: AdminView },
    { path: '/game/:id', name: 'game', component: ChatPreview },
    { path: '/adventures/new', name: 'adventure-create', component: () => import('../../src/views/CreateAdventureView.vue') },
    { path: '/adventures/:adventureId/editor', name: 'adventure-editor', props: true, component: () => import('../../src/views/AdventureEditorView.vue') },
    { path: '/adventures/:adventureId/editor/scenes/:sceneId', name: 'adventure-editor-scene', props: true, component: () => import('../../src/views/AdventureEditorView.vue') },
    { path: '/adventures/:adventureId/editor/exits/:exitId', name: 'adventure-editor-exit', props: true, component: () => import('../../src/views/AdventureEditorView.vue') },
    { path: '/login', name: 'login', component: () => import('../../src/views/LoginView.vue') },
  ],
})
if (params.get('role') === 'user') fixture.user.role = 'user'
router.beforeEach(to => to.name === 'admin' && fixture.user.role !== 'admin' ? { name: 'portal' } : true)
if (['simple', 'advanced'].includes(params.get('mode') || '')) localStorage.setItem('tw_generator_mode', params.get('mode')!)
const initial = loginPreview ? '/login' : params.get('screen') === 'create' ? '/adventures/new' : params.get('screen') === 'editor' ? `/adventures/${params.get('adventure') || 'coast'}/editor` : params.get('section') === 'admin' ? '/admin' : { path: '/', query: { section: params.get('section') || 'templates' } }
await router.push(initial)
createApp({ setup: () => () => h('div', { class: 'h-dvh flex flex-col bg-slate-950 text-slate-200 font-ui' }, [
  h('div', { class: 'flex min-h-7 shrink-0 items-center justify-between gap-3 border-b border-slate-800 px-4 py-1 text-[11px] text-slate-400' }, [h('span', loginPreview ? 'Fictional sign-in · Storykeeper / preview-only · recovery code DEMO1-DEMO2' : 'Interactive preview · fictional data · changes reset on reload'), h('a', { href: chatHref, class: 'shrink-0 text-amber-200 hover:underline' }, 'Chat preview ↗')]),
  h(GlobalHeader), h('div', { class: 'min-h-0 flex-1' }, h(RouterView)),
]) }).use(router).mount('#app')
