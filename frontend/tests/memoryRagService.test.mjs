import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import ts from 'typescript'

const requests = []
let response = { ok: true, json: async () => ({ enabled: false, key_configured: true }) }
const httpModule = `data:text/javascript;base64,${Buffer.from('export const mock = {}; export const apiFetch = (...args) => mock.fetch(...args)').toString('base64')}`
const { mock } = await import(httpModule)
mock.fetch = async (path, options) => {
  requests.push({ path, ...options })
  return response
}
const source = readFileSync(new URL('../src/services/memoryRagService.ts', import.meta.url), 'utf8')
const compiled = ts
  .transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
  })
  .outputText.replace("from '@/services/http'", `from '${httpModule}'`)
const { memoryRagPayload, memoryRagService: service } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`
)
const settings = {
  enabled: false,
  provider: 'ollama',
  base_url: ' http://localhost:11434 ',
  model: ' nomic-embed-text ',
  timeout_seconds: 10,
  key_configured: true
}

test('blank key preserves saved secret and public key metadata never becomes a write field', () => {
  assert.deepEqual(memoryRagPayload(settings, '  '), {
    enabled: false,
    provider: 'ollama',
    base_url: 'http://localhost:11434',
    model: 'nomic-embed-text',
    timeout_seconds: 10
  })
  assert.equal(memoryRagPayload(settings, ' replacement-secret ').api_key, 'replacement-secret')
})

test('memory settings and real embeddings test use independent endpoints and explicit opt-in', async () => {
  requests.length = 0
  await service.getSettings()
  await service.saveSettings(memoryRagPayload(settings, ''))
  await service.testSettings(memoryRagPayload({ ...settings, enabled: true }, 'test-key'))
  assert.deepEqual(
    requests.map(({ path, method }) => [path, method]),
    [
      ['/settings/memory-rag', 'GET'],
      ['/settings/memory-rag', 'PUT'],
      ['/settings/memory-rag/test', 'POST']
    ]
  )
  assert.equal(JSON.parse(requests[1].body).enabled, false)
  assert.equal(JSON.parse(requests[2].body).api_key, 'test-key')
  assert.equal(requests[2].timeoutMs, 20000)
})

test('clear and rebuild target only the selected adventure memory index', async () => {
  requests.length = 0
  await service.getIndex('world/a')
  await service.clearIndex('world/a')
  await service.rebuildIndex('world/a')
  assert.deepEqual(
    requests.map(({ path, method }) => [path, method]),
    [
      ['/adventures/templates/world%2Fa/memory-index', 'GET'],
      ['/adventures/templates/world%2Fa/memory-index', 'DELETE'],
      ['/adventures/templates/world%2Fa/memory-index/rebuild', 'POST']
    ]
  )
})

test('upstream failures do not expose response bodies or credentials', async () => {
  response = { ok: false, status: 500, json: async () => ({ detail: 'private-key' }) }
  await assert.rejects(service.testSettings(memoryRagPayload(settings, 'private-key')), error => {
    assert.equal(error.message.includes('private-key'), false)
    assert.match(error.message, /Check your embeddings settings/)
    return true
  })
  response = { ok: false, status: 403 }
  await assert.rejects(service.clearIndex('someone-elses-world'), /permission/)
})
