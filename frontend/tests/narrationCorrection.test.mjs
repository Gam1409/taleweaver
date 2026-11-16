import { test } from 'node:test'
import assert from 'node:assert/strict'
import { corrections, correctionModuleUrl } from './correctionModule.mjs'

test('queue is session scoped, replaces instead of accumulating and requires acknowledgement', () => {
  corrections.queueCorrection('one', 'Sounds', 'Fewer sounds')
  const sent = corrections.getCorrection('one')
  assert.equal(corrections.getCorrection('two'), null)
  corrections.acknowledgeCorrection('one', sent, false)
  assert.equal(corrections.getCorrection('one').text, 'Fewer sounds')
  corrections.queueCorrection('one', 'Continuity', 'Check presence')
  corrections.acknowledgeCorrection('one', sent, true)
  assert.equal(corrections.getCorrection('one').text, 'Check presence')
  corrections.acknowledgeCorrection('one', corrections.getCorrection('one'), true)
  assert.equal(corrections.getCorrection('one'), null)
})

test('empty or oversized feedback never queues, and all five presets fit the request budget', () => {
  corrections.queueCorrection('invalid', 'Custom', ' ')
  corrections.queueCorrection('invalid', 'Custom', 'a'.repeat(2001))
  assert.equal(corrections.getCorrection('invalid'), null)
  assert.equal(corrections.correctionPresets.length, 5)
  for (const preset of corrections.correctionPresets) {
    assert.ok(preset.text.length < corrections.CORRECTION_MAX_LENGTH)
  }
})

test('queued feedback survives a reload in tab storage and removal clears it', async t => {
  const values = new Map()
  const previous = globalThis.sessionStorage
  globalThis.sessionStorage = {
    getItem: key => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  }
  t.after(() => { globalThis.sessionStorage = previous })
  corrections.queueCorrection('reload', 'Custom', 'Keep the character voice')
  const fresh = await import(`${correctionModuleUrl}#reload`)
  assert.equal(fresh.getCorrection('reload').text, 'Keep the character voice')
  fresh.clearCorrection('reload')
  assert.equal(values.size, 0)
})
