import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import ts from 'typescript'

const require = createRequire(import.meta.url)
function load(name, dependencies = {}) {
  const source = readFileSync(new URL(`../src/services/${name}.ts`, import.meta.url), 'utf8')
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const module = { exports: {} }
  new Function('require', 'module', 'exports', code)(
    key => dependencies[key] ?? require(key), module, module.exports,
  )
  return module.exports
}
function service(name, response) {
  const errors = load('apiErrors')
  const calls = []
  const http = { authHeaders: () => ({}), apiFetch: async (...args) => { calls.push(args); return response } }
  return { ...load(name, { '@/services/http': http, '@/services/apiErrors': errors }), calls }
}
const invalid = {
  detail: [{ loc: ['body', 'outfit_completion', 'outfit', 2, 'clothing', 'layer'],
    msg: 'Input should be less than or equal to 4', input: 'PRIVATE_INPUT', ctx: { secret: 'PRIVATE_CONTEXT' } }],
}
const target = { adventureId: 'A', targetType: 'npc', targetId: 'MIKI' }

test('saving an entity retains the field and HTTP status instead of object coercion', async () => {
  const f = service('entityService', { ok: false, status: 422, json: async () => invalid })
  await assert.rejects(f.entityService.saveEntityText('A', { target_type: 'npc', target_id: 'MIKI' }), error => {
    assert.match(error.message, /HTTP 422/)
    assert.match(error.message, /outfit_completion\.outfit\.2\.clothing\.layer/)
    assert.match(error.message, /less than or equal to 4/)
    assert.doesNotMatch(error.message, /\[object Object\]|PRIVATE_INPUT|PRIVATE_CONTEXT/)
    return true
  })
  assert.equal(f.calls.length, 1)
})

test('clothing generation reports request validation without retrying or saving', async () => {
  const f = service('characterOutfits', { ok: false, status: 422, json: async () => ({
    detail: [{ loc: ['body', 'description'], msg: 'String should have at most 1000 characters' }],
  }) })
  await assert.rejects(f.generateCharacterOutfit(target, { brief: '' }), error => {
    assert.match(error.message, /generate clothing/i)
    assert.match(error.message, /HTTP 422.*description.*1000/)
    return true
  })
  assert.equal(f.calls.length, 1)
  assert.match(f.calls[0][0], /generate-character-outfit$/)
})

test('structured server messages reach clothing generation and item/NPC authoring', async () => {
  const response = { ok: false, status: 409, json: async () => ({
    detail: { message: 'The adventure changed. Reload before retrying.', raw: 'PRIVATE_DATA' },
  }) }
  const outfits = service('characterOutfits', response)
  const items = service('itemGeneration', response)
  const npcs = service('npcCreation', response)
  for (const call of [
    () => outfits.generateCharacterOutfit(target, { brief: '' }),
    () => items.generateItemDraft('A', 'A coat', 'WEARABLE', ['Chest']),
    () => npcs.generateNpcDraft('A', { brief: 'A doctor' }),
  ]) {
    await assert.rejects(call(), error => {
      assert.match(error.message, /HTTP 409.*adventure changed/)
      assert.doesNotMatch(error.message, /\[object Object\]|PRIVATE_DATA/)
      return true
    })
  }
})

test('malformed or unknown error bodies retain an actionable fallback and HTTP code', async () => {
  for (const body of [null, { detail: { input: 'PRIVATE_DATA' } }, { detail: [null, {}, 1] }]) {
    const f = service('characterOutfits', { ok: false, status: 502, json: async () => body })
    await assert.rejects(f.generateCharacterOutfit(target, {}), error => {
      assert.match(error.message, /generate clothing.*HTTP 502/i)
      assert.doesNotMatch(error.message, /\[object Object\]|PRIVATE_DATA|TypeError/)
      return true
    })
  }
  const f = service('entityService', { ok: false, status: 502, json: async () => { throw new Error('PRIVATE_DATA') } })
  await assert.rejects(f.entityService.saveEntityText('A', {}), /Failed to save entity text.*HTTP 502/)
})

test('successful draft requests retain their data and explicit model-call deadline', async () => {
  const draft = { draft: { appearance: null, outfit: [] }, context: { owned: [] }, notes: [] }
  const f = service('characterOutfits', { ok: true, json: async () => draft })
  assert.equal(await f.generateCharacterOutfit(target, { brief: 'Keep the coat.' }), draft)
  assert.equal(f.calls[0][1].timeoutMs, null)
  assert.equal(f.calls[0][1].method, 'POST')
})

test('plain server instructions are retained and recursive unknown details stay bounded', async () => {
  const instructions = 'Generation is unconfirmed. Check the inference queue before retrying.'
  const f = service('characterOutfits', { ok: false, status: 503, json: async () => ({ detail: instructions }) })
  await assert.rejects(f.generateCharacterOutfit(target, {}), error => {
    assert.ok(error.message.includes(instructions))
    return true
  })
  const { apiErrorMessage } = load('apiErrors')
  const cyclic = {}
  cyclic.detail = cyclic
  assert.equal(apiErrorMessage(cyclic, 'Could not generate clothing', 502), 'Could not generate clothing (HTTP 502)')
})
