import { test } from 'node:test'
import assert from 'node:assert/strict'
import { fixture, snapshot, tick } from './sessionHarness.mjs'

test('state refresh opts out of history while retaining the displayed transcript', async t => {
  const f = await fixture(t)
  const before = [...f.game.messages.value]
  f.route(async () => new Response(JSON.stringify({ ...snapshot([]), history_included: false, sheet: { hp: 83 } })))
  await f.game.refreshSession()
  assert.match(String(f.requests.at(-1).url), /include_messages=false/)
  assert.deepEqual(f.game.messages.value, before)
  assert.equal(f.game.sheet.value.hp, 83)
  assert.doesNotMatch(String(f.requests[0].url), /include_messages=false/)
})

test('periodic polls request state without retransmitting the story', async t => {
  const callbacks = []
  t.mock.method(globalThis, 'setInterval', callback => { callbacks.push(callback); return 0 })
  const f = await fixture(t)
  const before = [...f.game.messages.value]
  f.route(async () => new Response(JSON.stringify({ ...snapshot([]), history_included: false })))
  callbacks.at(-1)()
  await tick()
  await tick()
  assert.match(String(f.requests.at(-1).url), /include_messages=false/)
  assert.deepEqual(f.game.messages.value, before)
})

test('an initial full load rejects an explicitly incomplete transcript', async t => {
  const f = await fixture(t)
  f.route(async () => new Response(JSON.stringify({ ...snapshot([]), history_included: false })))
  await f.game.connect('session-b')
  assert.equal(f.game.status.value, 'error')
  assert.equal(f.requests.filter(request => request.options.method === 'POST').length, 0)
})
