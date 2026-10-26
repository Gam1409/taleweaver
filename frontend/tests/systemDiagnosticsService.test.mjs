/* eslint-env node */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import ts from 'typescript'

const calls = []
let response = { ok: true, json: async () => ({ enabled: false, log_directory: 'log', retention_files: 5 }) }
const httpModule = `data:text/javascript;base64,${Buffer.from('export const mock = {}; export const apiFetch = (...args) => mock.fetch(...args)').toString('base64')}`
const { mock } = await import(httpModule)
mock.fetch = async (...args) => { calls.push(args); return response }
const source = readFileSync(new URL('../src/services/systemDiagnosticsService.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
}).outputText.replace("from '@/services/http'", `from '${httpModule}'`)
const { systemDiagnosticsService: service } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`
)

test('loads current server state without accidentally enabling diagnostics', async () => {
  calls.length = 0
  const state = await service.getSettings()
  assert.equal(state.enabled, false)
  assert.deepEqual(calls, [['/system-diagnostics', {
    method: 'GET', includeJson: false, body: undefined
  }]])
})

test('enable and disable requests send only the explicit boolean', async () => {
  calls.length = 0
  await service.saveSettings(true)
  await service.saveSettings(false)
  assert.deepEqual(calls.map(([path, options]) => [path, options.method, JSON.parse(options.body)]), [
    ['/system-diagnostics', 'PUT', { enabled: true }],
    ['/system-diagnostics', 'PUT', { enabled: false }]
  ])
})

test('server errors never expose raw diagnostic details or secrets', async () => {
  response = { ok: false, status: 500, json: async () => { throw new Error('private player text and api key') } }
  await assert.rejects(service.saveSettings(true), error => {
    assert.match(error.message, /Could not update system diagnostics/)
    assert.doesNotMatch(error.message, /private|player|api key/)
    return true
  })
})

test('permission rejection is actionable and does not pretend the setting was saved', async () => {
  response = { ok: false, status: 403 }
  await assert.rejects(service.saveSettings(false), /Only administrators/)
})
