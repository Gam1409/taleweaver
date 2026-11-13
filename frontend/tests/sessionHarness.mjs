import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import ts from 'typescript'
import { correctionModuleUrl, corrections } from './correctionModule.mjs'
import { httpModule, sessionSnapshotModule } from './sessionSnapshotModule.mjs'
import { serverEventsModule } from './serverEventsModule.mjs'

const agentSettingsSource = readFileSync(new URL('../src/composables/useAgentSettings.ts', import.meta.url), 'utf8')
const agentSettingsModule = `data:text/javascript;base64,${Buffer.from(ts.transpileModule(agentSettingsSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText.replace("from '@/services/http'", `from '${httpModule}'`)).toString('base64')}`

const draftSource = readFileSync(new URL('../src/services/failedTurnDrafts.ts', import.meta.url), 'utf8')
const draftModule = ts.transpileModule(draftSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
}).outputText
const draftModuleUrl = `data:text/javascript;base64,${Buffer.from(draftModule).toString('base64')}`
const pollerSource = readFileSync(new URL('../src/services/snapshotPoller.ts', import.meta.url), 'utf8')
const pollerCompiled = ts.transpileModule(pollerSource, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
const pollerUrl = `data:text/javascript;base64,${Buffer.from(pollerCompiled).toString('base64')}`
const source = readFileSync(new URL('../src/composables/useGameSocket.ts', import.meta.url), 'utf8')
const npcStatusSource = readFileSync(new URL('../src/composables/useNpcBehaviorStatus.ts', import.meta.url), 'utf8')
const npcStatusCompiled = ts.transpileModule(npcStatusSource, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText.replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
const npcStatusUrl = `data:text/javascript;base64,${Buffer.from(npcStatusCompiled).toString('base64')}`
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
}).outputText.replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replace("from '@/composables/useAgentSettings'", `from '${agentSettingsModule}'`)
  .replace("from '@/composables/useNpcBehaviorStatus'", `from '${npcStatusUrl}'`)
  .replace("from '@/services/narrationCorrection'", `from '${correctionModuleUrl}'`)
  .replace("from '@/services/snapshotPoller'", `from '${pollerUrl}'`)
  .replace("from '@/services/sessionSnapshot'", `from '${sessionSnapshotModule}'`)
  .replace("from '@/services/serverEvents'", `from '${serverEventsModule}'`)
  .replace("from '@/services/http'", `from '${httpModule}'`)
  .replace("from '@/services/failedTurnDrafts'", `from '${draftModuleUrl}'`)
  .replace(/import .* from '@\/composables\/usePromptSuggestions';/, `const usePromptSuggestions = () => ({ suggestionsLoading: ref(false), suggestionsError: ref(''), suggestionsNotice: ref(''), refreshSuggestions: async () => {}, resetSuggestionsRequest: () => {} });`)
  .replace(/import .* from '@\/composables\/useSessionContentLanguage';/, `const useSessionContentLanguage = () => ({ language: ref('English'), languageSaving: ref(false), setLanguage: async () => true });`)
  .replace(/import .* from '@\/composables\/useNotifications';/, `export const notifications = []; const useNotifications = () => ({ addNotification: (...args) => notifications.push(args) });`)
  .replace(/import .* from '@\/store\/auth';/, `const authState = { token: 'test-token', isAuthenticated: true };`)

let unique = 0
const initial = [{ id: 'opening', role: 'assistant', content: 'Opening' }]
const action = 'May I look around?'
const snapshot = (messages = initial) => ({ messages, scene_id: 'room', language: 'English' })
const saved = () => snapshot([...initial, { id: 'user-1', role: 'user', content: action }, { id: 'reply-1', role: 'assistant', content: 'A complete answer.' }])
const frame = (event, data) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
const tick = () => new Promise(resolve => setImmediate(resolve))
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }

async function fixture(t) {
  corrections.clearCorrection('session-a')
  globalThis.window = {
    setTimeout: (...args) => globalThis.setTimeout(...args),
    clearTimeout: id => globalThis.clearTimeout(id),
    setInterval: () => 1, clearInterval: () => {}, dispatchEvent: () => {}
  }
  const module = await import(`data:text/javascript;base64,${Buffer.from(compiled + `\n// ${unique++}`).toString('base64')}`)
  const game = module.useGameSocket()
  const requests = []
  let route = async () => new Response(JSON.stringify(snapshot()))
  t.mock.method(globalThis, 'fetch', async (url, options = {}) => {
    requests.push({ url, options })
    return route(url, options)
  })
  await game.connect('session-a')
  t.after(() => game.disconnect())
  return { game, requests, notifications: module.notifications, route: fn => { route = fn } }
}

function stream(signal) {
  let controller
  const body = new ReadableStream({ start(value) { controller = value } })
  signal?.addEventListener('abort', () => controller.error(new DOMException('Aborted', 'AbortError')), { once: true })
  return { response: new Response(body), send: text => controller.enqueue(new TextEncoder().encode(text)), end: () => controller.close() }
}
const completed = (final = {}) => new Response(frame('chunk', { content: 'A complete answer.' }) + frame('final', final))


export { initial, action, snapshot, saved, frame, tick, deferred, fixture, stream, completed }
