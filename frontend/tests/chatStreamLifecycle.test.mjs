/* eslint-env node, browser, es2020 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import ts from 'typescript'
import { correctionModuleUrl, corrections } from './correctionModule.mjs'

const draftSource = readFileSync(new URL('../src/services/failedTurnDrafts.ts', import.meta.url), 'utf8')
const draftModule = ts.transpileModule(draftSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
}).outputText
const draftModuleUrl = `data:text/javascript;base64,${Buffer.from(draftModule).toString('base64')}`
const source = readFileSync(new URL('../src/composables/useGameSocket.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
}).outputText.replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replace("from '@/services/narrationCorrection'", `from '${correctionModuleUrl}'`)
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

test('normal turns and full replay carry correction outside the player message', async t => {
  for (const replay of [false, true]) {
    const f = await fixture(t)
    corrections.queueCorrection('session-a', 'Sounds', 'Reduce vocal repetition.')
    f.route(async (_url, options) => {
      if (options.method !== 'POST') return new Response(JSON.stringify(saved()))
      const payload = JSON.parse(options.body)
      assert.equal(payload.content, action)
      assert.equal(payload.narration_correction, 'Reduce vocal repetition.')
      assert.equal(payload.replay_message_id, replay ? 'opening' : undefined)
      return completed({ narration_correction_applied: true })
    })
    await f.game.sendMessage(action, replay, replay ? 'opening' : undefined)
    assert.equal(corrections.getCorrection('session-a'), null)
    assert.ok(f.game.messages.value.every(m => !m.content.includes('Reduce vocal repetition.')))
    f.game.disconnect()
  }
})

test('incomplete replies and non-narrative commands retain queued correction', async t => {
  for (const final of [{ narration_incomplete: true, narration_correction_applied: false }, {}]) {
    const f = await fixture(t)
    corrections.queueCorrection('session-a', 'Sounds', 'Reduce vocal repetition.')
    f.route(async (_url, options) => options.method === 'POST' ? completed(final) : new Response(JSON.stringify(saved())))
    await f.game.sendMessage(action)
    assert.equal(corrections.getCorrection('session-a').text, 'Reduce vocal repetition.')
    f.game.disconnect()
  }
})

test('input stays busy through history reload and second send cannot abort first', async t => {
  const f = await fixture(t), reload = deferred()
  let signal
  f.route(async (_url, options) => {
    if (options.method === 'POST') { signal = options.signal; return completed() }
    return reload.promise
  })
  const pending = f.game.sendMessage(action)
  await tick()
  assert.equal(f.game.status.value, 'connecting')
  await f.game.sendMessage('Second action')
  assert.equal(f.requests.filter(r => r.options.method === 'POST').length, 1)
  assert.equal(signal.aborted, false)
  reload.resolve(new Response(JSON.stringify(saved())))
  await pending
  assert.equal(f.game.status.value, 'connected')
  assert.ok(f.game.messages.value.some(m => m.id === 'user-1'))
})

test('old request reload and finally cannot replace a newly opened session', async t => {
  const f = await fixture(t), oldReload = deferred()
  f.route(async (url, options) => options.method === 'POST' ? completed() : url.includes('session-b') ? new Response(JSON.stringify(snapshot([{ id: 'new-opening', role: 'assistant', content: 'New story' }]))) : oldReload.promise)
  const pending = f.game.sendMessage(action)
  await tick()
  await f.game.connect('session-b')
  oldReload.resolve(new Response(JSON.stringify(saved())))
  await pending
  assert.deepEqual(f.game.messages.value.map(m => m.content), ['New story'])
  assert.equal(f.game.status.value, 'connected')
})

test('healthy stream survives 90 seconds and heartbeats reset idle timeout', async t => {
  const f = await fixture(t)
  t.mock.timers.enable({ apis: ['setTimeout'] })
  let live, signal
  f.route(async (_url, options) => {
    if (!options.method) return new Response(JSON.stringify(saved()))
    signal = options.signal; live = stream(signal); return live.response
  })
  const pending = f.game.sendMessage(action)
  await tick()
  t.mock.timers.tick(100_000)
  assert.equal(signal.aborted, false)
  live.send(': keepalive\n\n')
  await tick()
  t.mock.timers.tick(100_000)
  assert.equal(signal.aborted, false)
  live.send(frame('final', {})); live.end()
  await pending
  assert.equal(f.game.turnError.value, null)
})

test('idle timeout preserves action and gives visible retry feedback', async t => {
  const f = await fixture(t)
  t.mock.timers.enable({ apis: ['setTimeout'] })
  f.route(async (_url, options) => options.method === 'POST' ? stream(options.signal).response : new Response(JSON.stringify(snapshot())))
  const pending = f.game.sendMessage(action)
  await tick(); t.mock.timers.tick(180_000); await pending
  assert.equal(f.game.turnError.value.action, action)
  assert.match(f.game.turnError.value.message, /inactive/)
  assert.ok(f.game.messages.value.some(m => m.role === 'user' && m.content === action))
  assert.equal(f.game.status.value, 'connected')
})

test('EOF feedback hides technical identifiers while keeping internal diagnostics', async t => {
  const f = await fixture(t)
  f.route(async (_url, options) => options.method === 'POST' ? new Response(frame('chunk', { content: 'Unfinished sentence' }), { headers: { 'x-taleweaver-turn-id': 'turn-test' } }) : new Response(JSON.stringify(snapshot())))
  await f.game.sendMessage(action)
  assert.equal(f.game.turnError.value.action, action)
  assert.match(f.game.turnError.value.message, /incomplete/)
  assert.doesNotMatch(f.game.turnError.value.message, /turn-test|Turn-ID/)
  assert.ok(f.game.debugLogs.value.some(entry => entry.content.includes('turn-test')))
  assert.ok(f.notifications.every(([message]) => !message.includes('turn-test')))
  assert.ok(f.game.messages.value.every(message => !message.content.includes('turn-test')))
  assert.ok(f.game.messages.value.some(m => m.content === 'Unfinished sentence'))
})

test('HTTP conflict preserves unsent action with server reason', async t => {
  const f = await fixture(t)
  f.route(async () => new Response(JSON.stringify({ detail: 'Session is busy' }), { status: 409 }))
  await f.game.sendMessage(action)
  assert.deepEqual(f.game.turnError.value, { message: 'Session is busy', action })
  assert.ok(f.game.messages.value.some(m => m.role === 'user' && m.content === action))
})

test('final snapshot missing the newly sent action cannot erase it', async t => {
  const f = await fixture(t)
  f.route(async (_url, options) => options.method === 'POST' ? completed() : new Response(JSON.stringify(snapshot())))
  await f.game.sendMessage(action)
  assert.equal(f.game.turnError.value.action, action)
  assert.ok(f.game.messages.value.some(m => m.role === 'user' && m.content === action))
})

test('committed incomplete narration warns without duplicate-action retry', async t => {
  const f = await fixture(t)
  f.route(async (_url, options) => options.method === 'POST' ? completed({ narration_incomplete: true, narration_warning: 'Model output limit reached; the turn was saved.' }) : new Response(JSON.stringify(saved())))
  await f.game.sendMessage(action)
  assert.equal(f.game.turnError.value, null)
  assert.ok(f.notifications.some(([text]) => /output limit/.test(text)))
  assert.ok(f.game.messages.value.some(m => /output limit/.test(m.content)))
})

test('earlier poll cannot overwrite a newer active turn', async t => {
  const f = await fixture(t), reload = deferred()
  let live
  f.route(async (_url, options) => {
    if (options.method === 'POST') { live = stream(options.signal); return live.response }
    return reload.promise
  })
  const refreshing = f.game.refreshSession(), pending = f.game.sendMessage(action)
  await tick()
  reload.resolve(new Response(JSON.stringify({ ...snapshot(), sheet: { name: 'STALE' } })))
  await refreshing
  assert.equal(f.game.sheet.value, null)
  assert.equal(f.game.status.value, 'connecting')
  f.route(async () => new Response(JSON.stringify(snapshot())))
  live.end(); await pending
})


test('lost final event recovers committed turn instead of offering duplicate-action retry', async t => {
  const f = await fixture(t)
  f.route(async (_url, options) => options.method === 'POST' ? new Response(frame('chunk', { content: 'Part of the answer' })) : new Response(JSON.stringify(saved())))
  await f.game.sendMessage(action)
  assert.equal(f.game.turnError.value, null)
  assert.ok(f.game.messages.value.some(m => m.id === 'reply-1' && m.content === 'A complete answer.'))
  assert.ok(f.notifications.some(([text]) => /saved turn was recovered/.test(text)))
})


for (const command of ['/playagent off', '/debug inventory']) {
  test(`successful ${command} does not require a persisted user receipt`, async t => {
    const f = await fixture(t)
    f.route(async (_url, options) => options.method === 'POST' ? new Response(frame('final', {})) : new Response(JSON.stringify(snapshot())))
    await f.game.sendMessage(command)
    assert.equal(f.game.turnError.value, null)
    assert.equal(f.game.status.value, 'connected')
  })
}


test('system debug visibility follows snapshots independently of gameplay debug', async t => {
  const f = await fixture(t)
  assert.equal(f.game.systemDebugEnabled.value, false)
  f.route(async () => new Response(JSON.stringify({ ...snapshot(), system_debug_enabled: true, sheet: { debug_mode: false } })))
  await f.game.refreshSession()
  assert.equal(f.game.systemDebugEnabled.value, true)
  f.route(async () => new Response(JSON.stringify({ ...snapshot(), system_debug_enabled: false, sheet: { debug_mode: true } })))
  await f.game.refreshSession()
  assert.equal(f.game.systemDebugEnabled.value, false)
  f.route(async () => new Response(JSON.stringify({ ...snapshot(), system_debug_enabled: true })))
  await f.game.refreshSession()
  f.game.disconnect()
  assert.equal(f.game.systemDebugEnabled.value, false)
})

test('full replay uses the normal stream and replaces the old exchange without duplicating the player message', async t => {
  const f = await fixture(t)
  f.game.messages.value = saved().messages
  const replacement = snapshot([...initial, { id: 'user-2', role: 'user', content: action }, { id: 'reply-2', role: 'assistant', content: 'New outcome.' }])
  f.route(async (_url, options) => {
    if (options.method === 'POST') {
      assert.equal(JSON.parse(options.body).replay_message_id, 'reply-1')
      return new Response(frame('replay_history', { messages: initial, content: action }) + frame('chunk', { content: 'New outcome.' }) + frame('final', {}))
    }
    return new Response(JSON.stringify(replacement))
  })
  await f.game.sendMessage(action, true, 'reply-1')
  assert.equal(f.game.messages.value.filter(m => m.role === 'user').length, 1)
  assert.equal(f.game.messages.value.at(-1).id, 'reply-2')
  assert.equal(f.game.turnError.value, null)
})

test('failed full replay reloads the restored original and does not offer to repeat it as a fresh action', async t => {
  const f = await fixture(t)
  f.game.messages.value = saved().messages
  f.route(async (_url, options) => options.method === 'POST'
    ? new Response(frame('replay_history', { messages: initial, content: action }) + frame('chunk', { content: 'Unfinished' }) + frame('replay_history', { messages: saved().messages }) + frame('error', { detail: 'The previous turn was restored.' }))
    : new Response(JSON.stringify(saved())))
  await f.game.sendMessage(action, true, 'reply-1')
  assert.equal(f.game.messages.value.at(-1).id, 'reply-1')
  assert.equal(f.game.turnError.value, null)
})


test('interrupted full replay never offers a fresh-action retry', async t => {
  const f = await fixture(t)
  f.game.messages.value = saved().messages
  f.route(async (_url, options) => options.method === 'POST'
    ? new Response(frame('replay_history', { messages: initial, content: action }) + frame('chunk', { content: 'Unfinished' }))
    : new Response(JSON.stringify(saved())))
  await f.game.sendMessage(action, true, 'reply-1')
  assert.equal(f.game.messages.value.at(-1).id, 'reply-1')
  assert.equal(f.game.turnError.value, null)
})

for (const manual of [false, true]) {
  test(`failed attempts keep one player message and one retry banner (manual=${manual})`, async t => {
    const f = await fixture(t)
    f.route(async () => new Response(frame('error', { detail: 'Please try again.' })))
    await f.game.sendMessage(action)
    for (let attempt = 0; attempt < 3; attempt++) {
      if (manual) await f.game.sendMessage(action)
      else await f.game.retryLastAction()
    }
    assert.deepEqual(f.game.messages.value.map(m => m.content), ['Opening', action])
    assert.equal(f.game.turnError.value.message, 'Please try again.')
    assert.equal(f.requests.filter(r => r.options.method === 'POST').length, 4)
  })
}

test('retry removes only failed local output while retaining persisted messages', async t => {
  const f = await fixture(t)
  let attempt = 0
  f.route(async (_url, options) => {
    if (options.method !== 'POST') return new Response(JSON.stringify(saved()))
    if (attempt++ === 0) return new Response(
      frame('system', { id: 'saved-note', content: 'Saved note' }) +
      frame('chunk', { content: 'Unfinished failed answer' }) +
      frame('error', { detail: 'Please try again.' })
    )
    assert.ok(f.game.messages.value.some(m => m.id === 'saved-note'))
    assert.ok(!f.game.messages.value.some(m => m.content === 'Unfinished failed answer'))
    assert.equal(f.game.messages.value.filter(m => m.role === 'user').length, 1)
    return completed()
  })
  await f.game.sendMessage(action)
  assert.ok(f.game.messages.value.some(m => m.content === 'Unfinished failed answer'))
  await f.game.retryLastAction()
  assert.equal(f.game.turnError.value, null)
  assert.deepEqual(f.game.messages.value.map(m => m.content), ['Opening', action, 'A complete answer.'])
})

test('a successful turn does not suppress an intentional repeated player message', async t => {
  const f = await fixture(t)
  f.route(async (_url, options) => options.method === 'POST' ? completed() : new Response(JSON.stringify(saved())))
  await f.game.sendMessage(action)
  f.route(async () => new Response(frame('error', { detail: 'Please try again.' })))
  await f.game.sendMessage(action)
  assert.equal(f.game.messages.value.filter(m => m.role === 'user').length, 2)
  assert.ok(f.game.messages.value.some(m => m.id === 'reply-1'))
})
