import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { httpModule } from './sessionSnapshotModule.mjs'

const compile = path => ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
}).outputText
const uri = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
const utils = uri(compile('../src/utils/editor_utils.ts'))
const service = uri(compile('../src/services/adventureService.ts')
  .replace("from '@/services/http'", `from '${httpModule}'`)
  .replace("from '@/utils/editor_utils'", `from '${utils}'`))
const { adventureService } = await import(service)

test('model-backed editor requests preserve the server-owned deadline', async t => {
  globalThis.window = { setTimeout: () => { throw new Error('A browser timer must not interrupt this model call') } }
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/api/adventures/example/generate-field')
    assert.equal(new Headers(options.headers).get('Authorization'), 'Bearer test-token')
    return new Response('{"generated_text":"A complete description."}')
  })
  assert.equal((await adventureService.generateTemplateField('example', { field: 'plot' })).generated_text, 'A complete description.')
})

test('editor and gameplay requests share authentication-expiry handling', async t => {
  const events = []
  globalThis.window = { setTimeout: globalThis.setTimeout, dispatchEvent: event => events.push(event.type) }
  t.mock.method(globalThis, 'fetch', async () => new Response('{}', { status: 401 }))
  await assert.rejects(adventureService.fetchAdventure('example'), /Failed to load/)
  assert.deepEqual(events, ['auth-unauthorized'])
})
