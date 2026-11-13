import { test } from 'node:test'
import assert from 'node:assert/strict'
import { fixture, snapshot, deferred, tick } from './sessionHarness.mjs'

const currentSnapshot = () => ({ ...snapshot(), sheet: { name: 'Example B', agent_active: false, agent_step_by_step: true } })
const oldSettings = () => Response.json({ agent_active: true, agent_step_by_step: false })

for (const destination of ['session-b', 'session-a']) test(`old Agent settings cannot overwrite a newly connected ${destination}`, async t => {
  const f = await fixture(t), response = deferred()
  f.game.sheet.value = { name: 'Example A', agent_active: true, agent_step_by_step: true }
  f.route(async (_url, options) => options.method === 'PATCH' ? response.promise : Response.json(currentSnapshot()))
  const pending = f.game.updateAgentSettings({ step_by_step: false })
  await tick()
  await f.game.connect(destination)
  response.resolve(oldSettings())
  assert.equal(await pending, false)
  assert.equal(f.game.sheet.value.name, 'Example B')
  assert.equal(f.game.sheet.value.agent_active, false)
  assert.equal(f.game.sheet.value.agent_step_by_step, true)
})

for (const outcome of ['error', 'network']) test(`old Agent settings ${outcome} cannot notify a different session`, async t => {
  const f = await fixture(t), response = deferred()
  f.route(async (_url, options) => options.method === 'PATCH' ? response.promise : Response.json(currentSnapshot()))
  const pending = f.game.updateAgentSettings({ step_by_step: false })
  await tick()
  await f.game.connect('session-b')
  response.resolve(outcome === 'error' ? Response.json({ detail: 'The old example setting was rejected.' }, { status: 409 }) : Promise.reject(new TypeError('Example connection failed.')))
  assert.equal(await pending, false)
  assert.deepEqual(f.notifications, [])
})

test('disconnect aborts every pending Agent setting request', async t => {
  const f = await fixture(t), first = deferred(), second = deferred(), signals = []
  f.route(async (_url, options) => { signals.push(options.signal); return signals.length === 1 ? first.promise : second.promise })
  const one = f.game.updateAgentSettings({ step_by_step: false })
  const two = f.game.updateAgentSettings({ monkey_mode: true })
  await tick()
  f.game.disconnect()
  const aborted = signals.every(signal => signal.aborted)
  first.resolve(oldSettings()); second.resolve(oldSettings())
  const outcomes = await Promise.all([one, two])
  assert.ok(aborted)
  assert.deepEqual(outcomes, [false, false])
  assert.equal(f.game.sheet.value, null)
  assert.deepEqual(f.notifications, [])
})

test('same-session disjoint setting responses still merge canonical committed state', async t => {
  const f = await fixture(t), first = deferred(), second = deferred()
  f.game.sheet.value = { name: 'Example A', agent_step_by_step: true }
  let count = 0
  f.route(async () => ++count === 1 ? first.promise : second.promise)
  const one = f.game.updateAgentSettings({ active: true })
  const two = f.game.updateAgentSettings({ personality: 'casual' })
  second.resolve(Response.json({ agent_active: false, agent_step_by_step: true, agent_personality: 'casual' }))
  assert.equal(await two, true)
  first.resolve(Response.json({ agent_active: true, agent_step_by_step: true, agent_personality: 'casual' }))
  assert.equal(await one, true)
  assert.equal(f.game.sheet.value.agent_active, true)
  assert.equal(f.game.sheet.value.agent_personality, 'casual')
})

test('current settings preserve the PATCH contract and report genuine failures', async t => {
  const f = await fixture(t)
  f.game.sheet.value = { name: 'Example A', agent_step_by_step: true }
  f.route(async () => Response.json({ agent_step_by_step: false, agent_personality: 'casual' }))
  assert.equal(await f.game.updateAgentSettings({ step_by_step: false }), true)
  const request = f.requests.at(-1)
  assert.equal(request.url, '/api/adventures/session-a/agent/settings')
  assert.equal(request.options.method, 'PATCH')
  assert.deepEqual(JSON.parse(request.options.body), { step_by_step: false })
  assert.equal(f.game.sheet.value.name, 'Example A')
  assert.equal(f.game.sheet.value.agent_step_by_step, false)
  f.route(async () => Response.json({ detail: 'Example validation failed.' }, { status: 400 }))
  assert.equal(await f.game.updateAgentSettings({ personality: 'unknown' }), false)
  assert.deepEqual(f.notifications, [['Example validation failed.', 'error']])
})

test('one same-session completion cannot clear another pending setting', async t => {
  const f = await fixture(t), old = deferred(), current = deferred()
  f.game.sheet.value = { name: 'Example A', agent_step_by_step: true }
  let count = 0
  f.route(async () => ++count === 1 ? old.promise : current.promise)
  const first = f.game.updateAgentSettings({ step_by_step: false })
  const second = f.game.updateAgentSettings({ monkey_mode: true })
  old.resolve(oldSettings())
  assert.equal(await first, true)
  assert.equal(f.game.sheet.value.agent_step_by_step, false)
  current.resolve(Response.json({ agent_step_by_step: true, agent_monkey_mode: true }))
  assert.equal(await second, true)
  assert.equal(f.game.sheet.value.agent_monkey_mode, true)
})
