import { test } from 'node:test'
import assert from 'node:assert/strict'
import { fixture, frame, snapshot, deferred, tick, completed } from './sessionHarness.mjs'

test('an admission refusal removes only the current optimistic input and stays visible until dismissed', async t => {
  const f = await fixture(t)
  const quote = 'I set down the red coat'
  const action = `I look around. ${quote}.`
  const reason = `You do not have this item in your inventory.\n“${quote}”`
  const history = [
    { id: 'older', role: 'user', content: action },
    { id: 'older-reply', role: 'assistant', content: 'The door opens.' },
  ]
  const gate = deferred()
  f.route(async (_url, options) => options.method === 'POST'
    ? gate.promise
    : Response.json({ ...snapshot(history), pending_turn: null }))
  await f.game.connect('session-a')
  const unsaved = { role: 'user', content: 'An unrelated local action.' }
  f.game.messages.value.push(unsaved)
  const sending = f.game.sendMessage(action)
  await tick()
  assert.equal(f.game.messages.value.at(-1).content, action)
  assert.equal(f.game.messages.value.at(-1).id, undefined)
  gate.resolve(new Response(frame('error', {
    code: 'impossible_player_item', quote, detail: reason, retryable: false,
  })))
  await sending
  assert.deepEqual(f.game.messages.value.map(message => message.id || message.content),
    ['older', 'older-reply', unsaved.content])
  assert.deepEqual(f.game.turnError.value, { action, message: reason, admission: 'edit' })
  await f.game.refreshSession()
  assert.equal(f.game.turnError.value.message, reason)
  await f.game.retryLastAction()
  assert.equal(f.requests.filter(request => request.options.method === 'POST').length, 1)
  f.game.cancelTurnError()
  await f.game.refreshSession()
  assert.equal(f.game.turnError.value, null)
})

test('a transient preflight outage permits retry and preserves one confirmed story exchange', async t => {
  const f = await fixture(t)
  const action = 'I put down the suitcase.'
  f.route(async () => new Response(frame('error', {
    code: 'item_check_unavailable', detail: 'Item checking is unavailable.', retryable: true,
  })))
  await f.game.sendMessage(action)
  assert.equal(f.game.turnError.value.admission, 'retry')
  assert.equal(f.game.messages.value.filter(message => message.role === 'user').length, 0)
  f.route(async (_url, options) => options.method === 'POST' ? completed({ saved_user_message_id: 'success' })
    : Response.json(snapshot([{ id: 'success', role: 'user', content: action }, { id: 'reply', role: 'assistant', content: 'Done.' }])))
  await f.game.retryLastAction()
  assert.equal(f.game.turnError.value, null)
  assert.deepEqual(f.game.messages.value.map(message => message.id), ['success', 'reply'])
  assert.equal(f.requests.filter(request => request.options.method === 'POST').length, 2)
})
