import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mountSfc, settle } from './mountSfc.mjs'

test('uncertain reservations show the cause and failure elapsed time, while old rows remain usable', async t => {
  const v = mountSfc('components/admin/InferenceQueue.vue', {}, {
    '@/services/http': { apiFetch: async () => new Response(JSON.stringify({ enabled: true, reservations: [
      { endpoint_id: 'one', token: 'one', started: 100, uncertain_at: 220, status: 'UNCERTAIN', reason: 'request_timeout' },
      { endpoint_id: 'legacy', token: 'legacy', started: 100, status: 'UNCERTAIN' },
    ] })) },
  })
  t.after(() => v.app.unmount())
  await settle()
  const text = v.all().filter(node => node.type === 'p').map(v.text).join('\n')
  assert.match(text, /request deadline expired/i)
  assert.match(text, /120 seconds after admission/)
  assert.match(text, /No cause was recorded/)
  assert.doesNotMatch(text, /restart to enable/)
  const clear = v.all().filter(node => node.type === 'button' && v.text(node).trim() === 'Clear stopped request')
  assert.equal(clear.length, 2)
  assert.equal(clear.every(button => button.props.disabled), true)
})
