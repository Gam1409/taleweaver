import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mountSfc, settle } from './mountSfc.mjs'

const component = 'components/game/DebugProseEvidence.vue'

test('evidence inspection is manual and cancels obsolete model reads on session change', async t => {
  const requests = []
  const fixture = mountSfc(component, { sessionId: 'one' }, {
    '@/services/http': { apiFetch: (url, options) => new Promise(resolve => { requests.push({ url, options, resolve }) }) },
  })
  t.after(() => fixture.app.unmount())
  assert.deepEqual(requests, [])
  fixture.button('Review latest turn').props.onClick()
  await settle()
  assert.equal(requests[0].url, '/adventures/one/prose-evidence')
  assert.equal(requests[0].options.timeoutMs, null)
  assert.equal(fixture.button('Reviewing…').props.disabled, true)
  fixture.props.sessionId = 'two'
  await settle()
  assert.equal(requests[0].options.signal.aborted, true)
  fixture.button('Review latest turn').props.onClick()
  requests[1].resolve(Response.json({ has_snapshot: true, sources: [
    { role: 'user', message_id: 'u', events: [], error: 'Player review unavailable.' },
    { role: 'assistant', message_id: 'a', events: [{ kind: 'posture', value: 'kneeling', actor_id: 'NPC',
      resolved: true, latest: true, prefix: 'She ', quote: 'knelt', suffix: '.' }] },
  ] }))
  requests[0].resolve(Response.json({ has_snapshot: true, sources: [] }))
  await settle()
  assert.ok(fixture.all().some(node => node.props.role === 'alert' && fixture.text(node) === 'Player review unavailable.'))
  assert.ok(fixture.all().some(node => node.type === 'mark' && fixture.text(node) === 'knelt'))
  assert.ok(fixture.all().some(node => node.type === 'blockquote' && fixture.text(node) === 'She knelt.'))
  assert.equal(fixture.button('Review latest turn').props.disabled, false)
})
