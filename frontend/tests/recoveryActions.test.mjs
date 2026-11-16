import { test } from 'node:test'
import assert from 'node:assert/strict'
import { nextTick, ref } from 'vue'
import { mountSfc, settle, stubComponent } from './mountSfc.mjs'
import { storyMessageModule } from './storyMessageModule.mjs'

const storyMessages = await import(storyMessageModule)

const icons = Object.fromEntries(['AlertTriangle', 'ArrowRight', 'CheckCircle2', 'Loader2',
  'RefreshCw', 'ShieldAlert', 'Wand2', 'Wrench', 'X', 'RotateCcw'].map(name => [name, stubComponent]))
const reply = (data, status = 200) => new Response(JSON.stringify(data), { status })
function browserGlobals(t) {
  for (const [key, value] of Object.entries({ window: { confirm: () => true },
    Document: class {}, ShadowRoot: class {} })) {
    const original = Object.getOwnPropertyDescriptor(globalThis, key)
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value })
    t.after(() => original ? Object.defineProperty(globalThis, key, original) : delete globalThis[key])
  }
}

test('empty AI Fix results offer a fresh request without enabling Apply', async t => {
  let retries = 0
  const v = mountSfc('components/editor/AIFixSuggestionsModal.vue', {
    open: true, proposals: [], loading: false, applying: false, selectedIndex: -1,
    findingCode: 'missing_outfit', findingMessage: 'Missing outfit', hasBackupConfirmed: true,
    onRetry: () => { retries++ },
  }, {
    'lucide-vue-next': icons,
    '@/composables/useDialogFocus': { useDialogFocus() {} },
    './FixPatchDetails.vue': { default: stubComponent },
  })
  t.after(() => v.app.unmount())
  const retry = v.button('Generate fresh suggestions')
  assert.ok(retry, 'An empty successful response must not strand the finding.')
  retry.props.onClick()
  assert.equal(retries, 1)
  assert.equal(v.button('Apply selected fix').props.disabled, true)
  v.props.loading = true
  await nextTick()
  assert.equal(v.button('Generate fresh suggestions'), undefined)
})

function replayFixture(t, apiFetch) {
  browserGlobals(t)
  const calls = []
  const socket = {
    status: ref('connected'), sheet: ref({}), inputLocked: ref(false),
    messages: ref([{ id: 'action', role: 'user', content: 'Open the window.' },
      { id: 'answer', role: 'assistant', content: 'The window opens.' }]),
    sendMessage: async (...args) => { calls.push(args) },
  }
  const v = mountSfc('components/game/ResponseActions.vue', { gameId: 'session', disabled: false }, {
    'lucide-vue-next': icons, '@/services/http': { apiFetch },
    '@/composables/useGameSocket': { useGameSocket: () => socket },
    './RegenerateMessageButton.vue': { default: stubComponent },
    '@/utils/storyMessages': storyMessages,
  })
  t.after(() => v.app.unmount())
  return { ...v, socket, calls }
}

test('snapshot check failures can be retried in place before replaying the saved action', async t => {
  let requests = 0
  const v = replayFixture(t, async () => ++requests === 1
    ? reply({}, 503) : reply({ available: true, message_id: 'answer' }))
  await settle()
  assert.equal(v.button('Regenerate turn').props.disabled, true)
  const retry = v.button('Retry turn check')
  assert.ok(retry, 'Checking a snapshot must be retryable without reopening the session.')
  retry.props.onClick()
  await settle()
  assert.equal(requests, 2)
  assert.equal(v.button('Regenerate turn').props.disabled, false)
  await v.button('Regenerate turn').props.onClick()
  assert.deepEqual(v.calls, [['Open the window.', true, 'answer']])
})

test('replay respects parent evaluation and input locks even after a successful check', async t => {
  const v = replayFixture(t, async () => reply({ available: true, message_id: 'answer' }))
  await settle()
  v.props.disabled = true
  await nextTick()
  assert.equal(v.button('Regenerate turn').props.disabled, true)
  await v.button('Regenerate turn').props.onClick()
  assert.deepEqual(v.calls, [])
  v.props.disabled = false
  v.socket.inputLocked.value = true
  await nextTick()
  assert.equal(v.button('Regenerate turn').props.disabled, true)
  await v.button('Regenerate turn').props.onClick()
  assert.deepEqual(v.calls, [])
})

test('late snapshot checks cannot enable replay for a different session', async t => {
  const pending = []
  const v = replayFixture(t, () => new Promise(resolve => pending.push(resolve)))
  v.props.gameId = 'different-session'
  await nextTick()
  pending[1](reply({}, 503))
  await settle()
  pending[0](reply({ available: true, message_id: 'answer' }))
  await settle()
  assert.equal(v.button('Regenerate turn').props.disabled, true)
  assert.ok(v.button('Retry turn check'))
})

function repairFixture(t, apiFetch) {
  browserGlobals(t)
  const v = mountSfc('components/game/DebugItemRepair.vue', {
    sessionId: 'session', itemId: 'COAT', name: 'Coat',
  }, { 'lucide-vue-next': icons, '@/services/http': { apiFetch },
    '@/utils/game_icons': { getImageUrl: value => value } })
  t.after(() => v.app.unmount())
  return v
}
const item = { name: 'White coat', description: 'A wool coat.', item_type: 'DEFAULT' }

test('item repair can recover from an initial load failure without closing the dialog', async t => {
  let requests = 0
  const v = repairFixture(t, async () => ++requests === 1
    ? reply({ detail: 'Temporarily unavailable.' }, 503)
    : reply({ before_hash: 'current', item }))
  await v.button('Repair').props.onClick()
  await nextTick()
  assert.equal(v.all().find(node => node.type === 'fieldset').props.disabled, true)
  const retry = v.button('Retry loading item')
  assert.ok(retry, 'A failed load must have a visible recovery action.')
  await retry.props.onClick()
  await nextTick()
  assert.equal(requests, 2)
  assert.equal(v.all().find(node => node.type === 'fieldset').props.disabled, false)
  assert.equal(v.all().find(node => node.type === 'textarea').value, item.description)
})

test('a stale item repair reloads its baseline only after confirmation and clears old image drafts', async t => {
  const calls = []
  const v = repairFixture(t, async (url, init) => {
    calls.push({ url, init })
    if (url.endsWith('/image')) return reply({ image_url: '/old-preview.png' })
    if (url.endsWith('/preview')) return calls.filter(call => call.url.endsWith('/preview')).length === 1
      ? reply({ detail: 'The item or its owner changed.' }, 409) : reply({ values: item })
    return reply({ before_hash: calls.length === 1 ? 'old' : 'new', item })
  })
  await v.button('Repair').props.onClick()
  await v.button('Generate image preview').props.onClick()
  await v.button('Generate text & technical draft').props.onClick()
  await nextTick()
  const reload = v.button('Reload saved item')
  assert.ok(reload, 'A stale before_hash cannot be repaired by generating with the same hash.')
  globalThis.window.confirm = () => false
  await reload.props.onClick()
  assert.equal(calls.length, 3)
  assert.ok(v.all().some(node => node.type === 'img'))
  globalThis.window.confirm = () => true
  await reload.props.onClick()
  await nextTick()
  assert.equal(v.all().some(node => node.type === 'img'), false)
  await v.button('Generate text & technical draft').props.onClick()
  assert.equal(JSON.parse(calls.at(-1).init.body).before_hash, 'new')
  assert.equal(calls.some(call => call.url.endsWith('/apply')), false)
})
