import { Buffer } from 'node:buffer'
import { readFileSync } from 'node:fs'
import { effectScope } from 'vue'
import ts from 'typescript'

let sequence = 0

function moduleUrl(code) {
  return `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
}

function compile(path, imports = {}) {
  const source = readFileSync(new URL(`../src/${path}.ts`, import.meta.url), 'utf8')
  let code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 }
  }).outputText
  for (const [name, url] of Object.entries({ vue: import.meta.resolve('vue'), ...imports })) {
    code = code.replaceAll(`from '${name}'`, `from '${url}'`)
  }
  return moduleUrl(code)
}

export async function portalDataFixture(t, overrides = {}) {
  const key = `portalData${sequence++}`
  const tone = { id: 'heroic-epic', name: 'Heroic & Epic', instruction: 'A hopeful quest.' }
  const templates = [{ template_id: 'archive', title: 'Archive', is_ready: true, selected_tone: tone }]
  const sessions = ['A', 'B'].map(game_id => ({
    game_id, template_id: 'archive', adventure_title: 'Archive', status: 'active',
    status_note: `Original ${game_id}`, selected_tone: tone
  }))
  const calls = []
  const api = {
    listAdventureTemplates: async () => structuredClone(templates),
    listSessions: async () => structuredClone(sessions),
    getSettings: async () => ({ tone_catalog: [tone], image_styles_catalog: [] }),
    updateSession: async (id, payload) => {
      calls.push({ id, payload })
      return { ...sessions.find(row => row.game_id === id), ...payload }
    },
    ...overrides
  }
  globalThis[key] = api
  const apiUrl = moduleUrl(`export const api=globalThis['${key}'];`)
  const status = compile('services/statusPoller')
  const pending = compile('composables/usePortalPendingState', {
    '@/composables/useApi': apiUrl,
    '@/services/statusPoller': status
  })
  const modals = compile('composables/usePortalModals')
  const url = compile('composables/usePortalData', {
    '@/composables/useApi': apiUrl,
    '@/services/notificationService': moduleUrl('export const notificationService={};'),
    '@/composables/usePortalPendingState': pending,
    '@/composables/usePortalModals': modals
  })
  const { usePortalData } = await import(url)
  const filters = await import(compile('composables/usePortalFilters'))
  const storage = new Map()
  const originalStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
    getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value)
  } })
  const scope = effectScope()
  const data = scope.run(() => usePortalData())
  t.after(() => {
    scope.stop()
    delete globalThis[key]
    if (originalStorage) Object.defineProperty(globalThis, 'localStorage', originalStorage)
    else delete globalThis.localStorage
  })
  await data.fetchPortalData()
  return { data, filters, scope, tone, templates, sessions, api, calls }
}

export function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
