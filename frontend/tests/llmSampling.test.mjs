import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const source = readFileSync(new URL('../src/services/llmSampling.ts', import.meta.url), 'utf8')
const code = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
const { normalizeSampling, effectiveSampling, toggleRoleSampling, SAMPLING_FIELDS } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)

test('legacy settings keep all sampler fields unset and zero remains explicit', () => {
  const value = normalizeSampling()
  assert.equal(value.defaults.temperature, null)
  assert.equal(value.defaults.local_extensions, false)
  assert.deepEqual(value.roles, {})
  const zero = normalizeSampling({ defaults: { temperature: 0, top_k: 0, min_p: 0 } })
  assert.equal(zero.defaults.temperature, 0)
  assert.equal(zero.defaults.top_k, 0)
  assert.equal(zero.defaults.min_p, 0)
})

test('narrative and technical profiles copy shared values once and then stay independent', () => {
  const shared = normalizeSampling({ defaults: { temperature: 0.7, top_p: 0.9 } })
  let next = toggleRoleSampling(shared, 'complex', true)
  next = toggleRoleSampling(next, 'small', true)
  next.roles.complex.profile.temperature = 1.05
  next.roles.small.profile.temperature = 0.15
  assert.equal(effectiveSampling(next, 'complex').temperature, 1.05)
  assert.equal(effectiveSampling(next, 'small').temperature, 0.15)
  next.defaults.temperature = 0.8
  assert.equal(effectiveSampling(next, 'compression').temperature, 0.8)
  assert.equal(effectiveSampling(next, 'complex').temperature, 1.05)
  assert.equal(shared.defaults.temperature, 0.7)
  assert.deepEqual(shared.roles, {})
})

test('disabling and re-enabling a role preserves its draft and blank bypasses shared defaults', () => {
  let value = normalizeSampling({ defaults: { temperature: 0.7 } })
  value = toggleRoleSampling(value, 'complex', true)
  value.roles.complex.profile.temperature = null
  assert.equal(effectiveSampling(value, 'complex').temperature, null)
  value = toggleRoleSampling(value, 'complex', false)
  assert.equal(effectiveSampling(value, 'complex').temperature, 0.7)
  value = toggleRoleSampling(value, 'complex', true)
  assert.equal(effectiveSampling(value, 'complex').temperature, null)
})

test('normalization and unsaved connection profiles never alias the stored object', () => {
  const saved = normalizeSampling()
  const draft = normalizeSampling(saved)
  draft.defaults.min_p = 0.1
  const testProfile = effectiveSampling(draft, 'small')
  testProfile.min_p = 0.2
  assert.equal(saved.defaults.min_p, null)
  assert.equal(draft.defaults.min_p, 0.1)
})

test('every control explains its effect and neutral/filter semantics', () => {
  assert.deepEqual(SAMPLING_FIELDS.map(field => field.label), ['Temperature', 'Top P', 'Top K', 'Min P', 'Repetition penalty'])
  assert.ok(SAMPLING_FIELDS.every(field => field.help.length > 100))
  assert.match(SAMPLING_FIELDS.find(field => field.key === 'repetition_penalty').help, /One is neutral/)
})
