import { createApp, h, ref } from 'vue'
import '../../src/assets/main.css'
import NarratorSettings from '../../src/components/game/NarratorSettings.vue'

const legacy = () => ({ voice: null, verbosity: 'default' })
const saved = new Map<string, unknown>([
  ['/adventures/session-one/narrator-settings', legacy()],
  ['/adventures/session-two/narrator-settings', legacy()],
  ['/adventures/blueprint/narrator-defaults', legacy()],
])
const voice = { id: 'clear_voice', name: 'Clear voice', description: 'Clear, unhurried prose.', instruction: 'Use clear, unhurried prose.', sample: 'The coast was quiet.' }
const writes: { path: string; body: any }[] = [], unhandled: string[] = []
let fail = false
const originalFetch = window.fetch.bind(window)
window.fetch = async (input, options) => {
  const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
  const url = new URL(raw, location.origin)
  if (!url.pathname.startsWith('/api/')) return originalFetch(input, options)
  const path = url.pathname.slice(4)
  if (!saved.has(path)) {
    unhandled.push(path)
    return Response.json({ detail: 'Unknown fixture operation.' }, { status: 501 })
  }
  if (options?.method === 'PUT') {
    const body = JSON.parse(String(options.body))
    writes.push({ path, body })
    if (fail) { fail = false; return Response.json({ detail: 'Please retry saving.' }, { status: 503 }) }
    saved.set(path, structuredClone(body))
  }
  return Response.json({ settings: saved.get(path), voices: [voice] })
}
Object.assign(window, { narrationFlowFixture: { writes, unhandled, failNextSave: () => { fail = true } } })

createApp({ setup() {
  const endpoint = ref('/adventures/session-one/narrator-settings')
  const session = ref<InstanceType<typeof NarratorSettings> | null>(null)
  const status = ref('')
  const save = async () => { status.value = await session.value?.save() ? 'Session preferences saved.' : 'Session save failed.' }
  const button = 'rounded-xl border border-slate-600 px-3 py-2 text-sm'
  return () => h('main', { class: 'h-dvh overflow-y-auto bg-slate-950 p-3 text-slate-200 sm:p-6' }, [
    h('div', { class: 'mx-auto grid max-w-5xl gap-6 lg:grid-cols-2' }, [
      h('p', { class: 'text-sm text-slate-400 lg:col-span-2' }, 'Narrator preferences · fictional data · no generation requests'),
      h('section', { 'aria-label': 'Session narration', class: 'min-w-0 space-y-3' }, [
        h('h2', { class: 'font-semibold' }, 'Session narration'),
        h(NarratorSettings, { ref: session, endpoint: endpoint.value }),
        h('div', { class: 'flex flex-wrap gap-3' }, [
          h('button', { class: button, onClick: save }, 'Save session'),
          h('button', { class: button, onClick: () => { endpoint.value = endpoint.value.includes('session-one') ? '/adventures/session-two/narrator-settings' : '/adventures/session-one/narrator-settings'; status.value = '' } }, 'Switch session'),
        ]),
        h('p', { role: 'status', class: 'text-sm' }, status.value),
      ]),
      h('section', { 'aria-label': 'Adventure narrator defaults', class: 'min-w-0 space-y-3' }, [
        h('h2', { class: 'font-semibold' }, 'Adventure narrator defaults'),
        h(NarratorSettings, { endpoint: '/adventures/blueprint/narrator-defaults', authorDefaults: true }),
      ]),
    ]),
  ])
} }).mount('#app')
