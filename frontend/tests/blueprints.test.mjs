import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import ts from 'typescript'

const source = readFileSync(new URL('../src/services/blueprints.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText.replace(/import .* from '@\/services\/http';/, 'const apiFetch = (...args) => globalThis.fetch(...args);')
const { blueprintOptions, checkBlueprint } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

test('preflight forwards only mode, size and generation controls', () => {
  assert.deepEqual(blueprintOptions({ rule_enforcement_mode: 'vn', max_scenes: 3, title: 'Private draft', key: 'secret', storyIdea: 'large text' }), { rule_enforcement_mode: 'vn', max_scenes: 3 })
})

test('preflight keeps exact blueprint text and returns line diagnostics', async t => {
  const text = '[NPC: LENA] Lena\nage: -1'
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/adventures/blueprint/validate')
    assert.deepEqual(JSON.parse(options.body), { text, options: { max_scenes: 2 } })
    return new Response(JSON.stringify({ has_tags: true, errors: [{ line: 2, message: 'Age invalid', severity: 'error' }], warnings: [], counts: {} }))
  })
  const result = await checkBlueprint(text, { max_scenes: 2 })
  assert.equal(result.errors[0].line, 2)
})
