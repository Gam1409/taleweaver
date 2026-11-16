import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mountSfc, settle, stubComponent } from './mountSfc.mjs'

async function inspect(items) {
  const calls = []
  const fixture = mountSfc('components/game/immersive/SessionStateChecks.vue', { sessionId: 'session' }, {
    '@/services/http': {
      apiFetch: async url => {
        calls.push(url)
        return { ok: true, json: async () => ({ mode: 'vn', items, arrival: null }) }
      },
    },
    'lucide-vue-next': { ClipboardCheck: stubComponent },
  })
  fixture.button('Item and travel checks').props.onClick()
  await settle()
  return { ...fixture, calls }
}

const rejected = {
  status: 'complete', reason: '', error_type: '', message_id: 'turn', accepted: [],
  rejected: ['SCARF: Item quote is not an exact contiguous substring of the completed narration.'],
}

test('owner can inspect the rejected quote and action basis without another model request', async () => {
  const fixture = await inspect({ ...rejected, rejected_details: [{
    label: 'SCARF', reason: rejected.rejected[0], basis: 'completed',
    evidence: '<img src=x onerror=evil()> A proposed quote.',
  }] })
  try {
    const text = fixture.all().map(fixture.text).join(' ')
    assert.match(text, /Rejected proposal details/)
    assert.match(text, /Action basis: completed/)
    assert.match(text, /A proposed quote/)
    assert.match(text, /not accepted as evidence/)
    assert.ok(!fixture.all().some(node => node.type === 'img'))
    assert.deepEqual(fixture.calls, ['/adventures/session/state-checks'])
  } finally {
    fixture.app.unmount()
  }
})

test('legacy item checks retain their rejection message without invented quote details', async () => {
  const fixture = await inspect(rejected)
  try {
    const text = fixture.all().map(fixture.text).join(' ')
    assert.match(text, /Not applied: SCARF/)
    assert.doesNotMatch(text, /Rejected proposal details|Action basis:/)
  } finally {
    fixture.app.unmount()
  }
})

test('failed schema check shows saved fields and constraints without another request', async () => {
  const fixture = await inspect({ ...rejected, status: 'failed', rejected: [], failure: {
    code: 'invalid_schema', reason: 'Invalid garment data.',
    validation_fields: ['actions.1.new_item.wearable_slots'],
    validation_details: [{ field: 'actions.1.new_item.wearable_slots', code: 'too_short',
      reason: 'Value must contain at least 1 items.' }],
  } })
  try {
    const text = fixture.all().map(fixture.text).join(' ')
    assert.match(text, /Invalid garment data/)
    assert.match(text, /actions\.1\.new_item\.wearable_slots/)
    assert.match(text, /at least 1/)
    assert.deepEqual(fixture.calls, ['/adventures/session/state-checks'])
  } finally {
    fixture.app.unmount()
  }
})

test('legacy schema check retains its known fields without inventing a constraint', async () => {
  const fixture = await inspect({ ...rejected, status: 'failed', rejected: [], failure: {
    code: 'invalid_schema', reason: 'Invalid item data.', validation_fields: ['actions.1.new_item'],
  } })
  try {
    const text = fixture.all().map(fixture.text).join(' ')
    assert.match(text, /actions\.1\.new_item/)
    assert.doesNotMatch(text, /at least 1/)
  } finally {
    fixture.app.unmount()
  }
})
