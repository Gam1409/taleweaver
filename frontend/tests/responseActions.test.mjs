import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { effectScope, reactive, ref, nextTick } from 'vue'
import ts from 'typescript'
import { storyMessageModule } from './storyMessageModule.mjs'

const source = readFileSync(new URL('../src/components/game/ResponseActions.vue', import.meta.url), 'utf8')
  .match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  .replace(/import[^\n]+\n/g, '')
  .replace(/const props = defineProps<[^\n]+\n/, '')
  .replace('const socket = useGameSocket()', '')
const code = ts.transpileModule(`import {computed,ref,watch,onScopeDispose} from '${import.meta.resolve('vue')}';
import {isStoryMessage} from '${storyMessageModule}';
export function setup(props, socket, apiFetch) { ${source}; return {available,latest,replay,undo,canUndo}; }`, {
  compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext}
}).outputText
const { setup } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)

test('full replay after debug toggles resends the story action and uses its saved reply', async t => {
  const calls = []
  const messages = ref([
    {id: 'action', role: 'user', content: 'Open the door.'},
    {id: 'reply', role: 'assistant', content: 'The door opens.'},
    {id: 'toggle', role: 'user', content: '/debug on'},
    {id: 'notice', role: 'system', content: 'Enabled.', is_debug: true},
  ])
  const socket = {messages, status: ref('connected'), sheet: ref({}), inputLocked: ref(false), sendMessage: async (...args) => calls.push(args)}
  const scope = effectScope()
  t.after(() => scope.stop())
  const f = scope.run(() => setup(reactive({gameId: 'session'}), socket, async () =>
    new Response(JSON.stringify({available: true, message_id: 'reply'}))))
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(f.available.value, true)
  const previousWindow = globalThis.window
  globalThis.window = { confirm: () => true }
  t.after(() => { globalThis.window = previousWindow })
  await f.replay()
  assert.deepEqual(calls, [['Open the door.', true, 'reply']])
  messages.value.push({id: 'pending', role: 'user', content: 'Look inside.'})
  await nextTick()
  assert.equal(f.available.value, false)
})

test('full turn undo is debug-only, confirmed and available after a terminal result', async t => {
  const calls = []
  const socket = {
    messages: ref([{id: 'reply', role: 'assistant', content: 'The last reply.'}]),
    status: ref('game_over'), sheet: ref({debug_mode: false}), inputLocked: ref(true),
    deleteMessage: async id => calls.push(id),
  }
  const scope = effectScope()
  t.after(() => scope.stop())
  const f = scope.run(() => setup(reactive({gameId: 'session'}), socket, async () =>
    new Response(JSON.stringify({available: true, message_id: 'reply'}))))
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(f.canUndo.value, false)
  socket.sheet.value.debug_mode = true
  assert.equal(f.canUndo.value, true)
  const previousWindow = globalThis.window
  t.after(() => { globalThis.window = previousWindow })
  globalThis.window = {confirm: () => false}
  await f.undo()
  assert.deepEqual(calls, [])
  globalThis.window.confirm = () => true
  await f.undo()
  assert.deepEqual(calls, ['reply'])
  socket.sheet.value.agent_active = true
  assert.equal(f.canUndo.value, false)
})
