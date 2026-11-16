import { test } from 'node:test'
import assert from 'node:assert/strict'
import { fixture, deferred, tick, snapshot } from './sessionHarness.mjs'

const before = { ...snapshot([{ id: 'opening', role: 'assistant', content: 'Before the action.' }]), sheet: { hp: 100, debug_mode: true }, scene_id: 'room-before' }

test('undo reloads authoritative character and scene state instead of filtering one message', async t => {
  const f = await fixture(t)
  f.game.sheet.value = { hp: 90, debug_mode: true }
  f.game.messages.value.push({ id: 'reply', role: 'assistant', content: 'The changed world.' })
  f.route(async (_url, options) => options.method === 'DELETE'
    ? new Response(JSON.stringify({ status: 'undone', deleted_messages: 2 }))
    : new Response(JSON.stringify(before)))
  await f.game.deleteMessage('reply')
  assert.equal(f.game.sheet.value.hp, 100)
  assert.deepEqual(f.game.messages.value.map(message => [message.id, message.content]), before.messages.map(message => [message.id, message.content]))
  assert.equal(f.requests.filter(request => request.options.method === 'DELETE').length, 1)
  assert.ok(f.requests.filter(request => request.options.method !== 'DELETE').length >= 2)
})

test('undo keeps input locked until the authoritative reload finishes', async t => {
  const f = await fixture(t), reload = deferred()
  f.route(async (_url, options) => options.method === 'DELETE'
    ? new Response(JSON.stringify({ status: 'undone', deleted_messages: 2 })) : reload.promise)
  const pending = f.game.deleteMessage('reply')
  try {
    await tick()
    assert.equal(f.game.status.value, 'loading')
    assert.equal(await f.game.runAgentTurn(), false)
  } finally {
    reload.resolve(new Response(JSON.stringify(before)))
    await pending
  }
  assert.equal(f.game.status.value, 'connected')
})

test('an undo response from the previous session cannot reopen it or notify in the new session', async t => {
  const f = await fixture(t), old = deferred()
  const next = snapshot([{ id: 'next-story', role: 'assistant', content: 'Another story.' }])
  f.route(async (_url, options) => options.method === 'DELETE' ? old.promise : new Response(JSON.stringify(next)))
  const pending = f.game.deleteMessage('reply')
  await tick()
  await f.game.connect('session-b')
  const afterNavigation = f.requests.length
  old.resolve(new Response(JSON.stringify({ status: 'undone', deleted_messages: 2 })))
  await pending
  assert.deepEqual(f.game.messages.value.map(message => [message.id, message.content]), next.messages.map(message => [message.id, message.content]))
  assert.equal(f.requests.length, afterNavigation)
  assert.deepEqual(f.notifications, [])
})

test('a missing snapshot preserves visible state and explains the checkpoint path', async t => {
  const f = await fixture(t)
  f.game.sheet.value = { hp: 90 }
  const messages = [...f.game.messages.value]
  f.route(async () => new Response(JSON.stringify({ detail: 'Use a Chronicles checkpoint from before this turn.' }), { status: 409 }))
  await f.game.deleteMessage('reply')
  assert.deepEqual(f.game.messages.value, messages)
  assert.equal(f.game.sheet.value.hp, 90)
  assert.equal(f.game.status.value, 'connected')
  assert.match(f.notifications[0][0], /checkpoint/)
})

test('undoing the first turn keeps empty history without generating a new prologue', async t => {
  const f = await fixture(t)
  f.route(async (_url, options) => options.method === 'DELETE'
    ? new Response(JSON.stringify({ status: 'undone', deleted_messages: 2 }))
    : new Response(JSON.stringify(snapshot([]))))
  await f.game.deleteMessage('reply')
  assert.deepEqual(f.game.messages.value, [])
  assert.equal(f.game.status.value, 'connected')
  assert.equal(f.requests.filter(request => request.options.method === 'POST').length, 0)
})

test('a failed reload after undo locks stale state and exposes the session recovery screen', async t => {
  const f = await fixture(t)
  f.route(async (_url, options) => options.method === 'DELETE'
    ? new Response(JSON.stringify({ status: 'undone', deleted_messages: 2 }))
    : new Response('Unavailable', { status: 503 }))
  await f.game.deleteMessage('reply')
  assert.equal(f.game.status.value, 'error')
  assert.equal(f.game.inputLocked.value, true)
  assert.match(f.game.sessionLoadError.value, /Reload the session/)
  const count = f.requests.length
  await f.game.sendMessage('Continue from the old world.')
  assert.equal(f.requests.length, count)
})

test('a server failure during undo leaves its outcome uncertain and requires recovery', async t => {
  const f = await fixture(t)
  f.route(async () => new Response(JSON.stringify({ detail: 'Server unavailable.' }), { status: 503 }))
  await f.game.deleteMessage('reply')
  assert.equal(f.game.status.value, 'error')
  assert.equal(f.game.inputLocked.value, true)
  assert.match(f.game.sessionLoadError.value, /Reload the session/)
  const count = f.requests.length
  await f.game.sendMessage('Continue from the old world.')
  assert.equal(f.requests.length, count)
})
