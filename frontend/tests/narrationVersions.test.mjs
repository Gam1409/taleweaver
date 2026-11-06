import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import { effectScope, reactive, ref, nextTick } from 'vue'
import ts from 'typescript'
import { storyMessageModule } from './storyMessageModule.mjs'

let sequence = 0
async function fixture(t, fetch) {
  const key = `versions${sequence++}`
  const props = reactive({ gameId: 'session' })
  const socket = { messages: ref([{ id: 'reply', role: 'assistant', content: 'Current' }]),
    status: ref('connected'), inputLocked: ref(false), sheet: ref({}) }
  const notices = []
  globalThis[key] = { props, socket, fetch, notices }
  let source = readFileSync(new URL('../src/components/game/NarrationVersions.vue', import.meta.url), 'utf8')
    .match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
    .replace(/import[\s\S]*?from ['"][^'"]+['"];?/g, '')
    .replace(/defineProps<[\s\S]*?>\(\)/, `globalThis['${key}'].props`)
  source = `import {computed,ref,watch,onScopeDispose} from '${import.meta.resolve('vue')}';
import {isStoryMessage} from '${storyMessageModule}';
const useGameSocket = () => globalThis['${key}'].socket;
const useNotifications = () => ({addNotification: (...args) => globalThis['${key}'].notices.push(args)});
const apiFetch = (...args) => globalThis['${key}'].fetch(...args);
export function setup() {${source}; return {request,dialog,selected,busy};}`
  const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  const module = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
  const scope = effectScope()
  const state = scope.run(module.setup)
  state.dialog.value = { showModal() {}, close() {} }
  t.after(() => { scope.stop(); delete globalThis[key] })
  return { ...state, socket, props, notices, scope }
}
const history = { current_revision_id: 'r2', versions: [
  {id: 'r1', content: 'Original', origin: 'original'}, {id: 'r2', content: 'Current', origin: 'rewrite'},
] }
const response = data => new Response(JSON.stringify(data))

test('restoring a version sends its revision fence and updates the same reply', async t => {
  const calls = []
  const f = await fixture(t, async (url, options) => {
    calls.push({url, options})
    return response(options.method === 'POST' ? {id: 'reply', role: 'assistant', content: 'Original'} : history)
  })
  await f.request()
  f.selected.value = 'r1'
  await f.request(true)
  assert.deepEqual(JSON.parse(calls[1].options.body), { version_id: 'r1', expected_revision_id: 'r2' })
  assert.equal(f.socket.messages.value[0].content, 'Original')
})

test('debug toggles do not change the narration whose versions are restored', async t => {
  const f = await fixture(t, async (url, options) => {
    assert.match(url, /\/chat\/reply\/versions/)
    return response(options.method === 'POST' ? {id: 'reply', role: 'assistant', content: 'Original'} : history)
  })
  f.socket.messages.value.push({id: 'debug', role: 'user', content: '/debug on'})
  await f.request()
  f.selected.value = 'r1'
  await f.request(true)
  assert.equal(f.socket.messages.value[0].content, 'Original')
  assert.equal(f.socket.messages.value[1].content, '/debug on')
})

test('stale restore keeps the current text and shows the server error', async t => {
  const f = await fixture(t, async (_url, options) => options.method === 'POST'
    ? new Response(JSON.stringify({detail: 'Reload versions'}), {status: 409}) : response(history))
  await f.request()
  f.selected.value = 'r1'
  await f.request(true)
  assert.equal(f.socket.messages.value[0].content, 'Current')
  assert.equal(f.notices[0][0], 'Reload versions')
})

test('changing session discards a late response', async t => {
  let finish
  const f = await fixture(t, () => new Promise(resolve => { finish = resolve }))
  const pending = f.request()
  f.props.gameId = 'other'
  await nextTick()
  finish(response(history))
  await pending
  assert.equal(f.selected.value, '')
  assert.equal(f.busy.value, false)
})
