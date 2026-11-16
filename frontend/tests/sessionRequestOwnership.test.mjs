import { test } from 'node:test'
import assert from 'node:assert/strict'
import { fixture, deferred, completed, tick, snapshot, saved, stream, frame } from './sessionHarness.mjs'

test('an old agent history reload must not replace a newly opened session', async t => {
  const f = await fixture(t), oldReload = deferred()
  f.route(async (url, options) => options.method === 'POST' ? completed() : url.includes('session-b')
    ? new Response(JSON.stringify(snapshot([{ id: 'new-opening', role: 'assistant', content: 'New story' }])))
    : oldReload.promise)
  const pending = f.game.runAgentTurn()
  await tick()
  await f.game.connect('session-b')
  oldReload.resolve(new Response(JSON.stringify(saved())))
  await pending
  assert.deepEqual(f.game.messages.value.map(message => message.content), ['New story'])
})

test('an old terminal epilogue must not append to a newly opened story', async t => {
  const f = await fixture(t), oldEnding = deferred()
  f.route(async (url, options) => options.method === 'POST' ? oldEnding.promise
    : new Response(JSON.stringify(snapshot([{ id: 'new-opening', role: 'assistant', content: 'New story' }]))))
  const pending = f.game.createTerminalEpilogue()
  await tick()
  await f.game.connect('session-b')
  oldEnding.resolve(new Response(JSON.stringify({ content: 'The old story ends here.' })))
  await pending
  assert.deepEqual(f.game.messages.value.map(message => message.content), ['New story'])
})

for (const kind of ['agent', 'epilogue']) {
  test(`a stale ${kind} response cannot unlock or cancel the new session request`, async t => {
    const f = await fixture(t)
    const oldResponse = deferred(), newResponse = deferred()
    const newStory = snapshot([{ id: 'new-opening', role: 'assistant', content: 'New story' }])
    let activeSignal
    f.route(async (url, options) => {
      if (url.includes('session-b')) {
        if (options.method === 'POST') { activeSignal = options.signal; return newResponse.promise }
        return new Response(JSON.stringify(newStory))
      }
      if (kind === 'agent' && options.method === 'POST') return completed()
      return oldResponse.promise
    })
    const oldRequest = kind === 'agent' ? f.game.runAgentTurn() : f.game.createTerminalEpilogue()
    await tick()
    await f.game.connect('session-b')
    const newRequest = f.game.runAgentTurn()
    await tick()
    oldResponse.resolve(new Response(JSON.stringify(kind === 'agent' ? saved() : { content: 'Old ending' })))
    await oldRequest
    assert.equal(f.game.status.value, 'connecting')
    assert.deepEqual(f.game.messages.value.map(message => message.content), ['New story'])
    assert.equal(activeSignal.aborted, false)
    f.game.haltActiveOperations()
    assert.equal(activeSignal.aborted, true)
    newResponse.resolve(completed())
    assert.equal(await newRequest, false)
  })
}

test('the agent keeps input locked until its authoritative reload finishes', async t => {
  const f = await fixture(t), reload = deferred()
  f.route(async (_url, options) => options.method === 'POST' ? completed() : reload.promise)
  const pending = f.game.runAgentTurn()
  await tick()
  assert.equal(f.game.status.value, 'connecting')
  reload.resolve(new Response(JSON.stringify(saved())))
  assert.equal(await pending, true)
  assert.equal(f.game.status.value, 'connected')
  assert.deepEqual(f.game.messages.value.map(message => message.content), saved().messages.map(message => message.content))
})

test('a successful terminal epilogue still updates its own session', async t => {
  const f = await fixture(t)
  f.route(async () => new Response(JSON.stringify({ content: 'The story ends here.' })))
  await f.game.createTerminalEpilogue()
  assert.equal(f.game.messages.value.at(-1).content, 'The story ends here.')
})

test('an agent authorization failure preserves the error status', async t => {
  const f = await fixture(t)
  f.route(async () => new Response('{}', { status: 401 }))
  assert.equal(await f.game.runAgentTurn(), false)
  assert.equal(f.game.status.value, 'error')
})

test('an agent error cannot unlock input while its stream is still open', async t => {
  const f = await fixture(t)
  let live
  f.route(async (_url, options) => {
    live = stream(options.signal)
    return live.response
  })
  const pending = f.game.runAgentTurn()
  await tick()
  live.send(frame('error', { detail: 'The turn failed.' }))
  await tick()
  assert.equal(f.game.status.value, 'connecting')
  assert.equal(await f.game.runAgentTurn(), false)
  live.end()
  assert.equal(await pending, false)
  assert.equal(f.game.status.value, 'connected')
  assert.equal(f.game.messages.value.filter(message => message.content === 'The turn failed.').length, 1)
})
