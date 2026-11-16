import { test } from 'node:test'
import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

async function module(name) {
  const source = readFileSync(new URL(`../src/services/${name}.ts`, import.meta.url), 'utf8')
  const code = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText.replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
  return import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
}
const { LLM_ROLES, customOpenAIUrl, useSharedApiUrlForAll } = await module('llmRoleEndpoints')
const { createEndpointModelCache } = await module('endpointModelCache')

test('all roles inherit the shared URL and a role override remains independent', () => {
  const form = { custom_openai_url: 'https://shared.example/v1/', complex_custom_openai_url: 'https://narrator.example/v1', complex_model_provider: 'custom_openai', complex_model: 'story' }
  for (const role of LLM_ROLES) assert.equal(customOpenAIUrl(form, role), role === 'complex' ? 'https://narrator.example/v1' : 'https://shared.example/v1')
  form.custom_openai_url = 'https://changed.example/v1'
  assert.equal(customOpenAIUrl(form, 'complex'), 'https://narrator.example/v1')
  useSharedApiUrlForAll(form)
  for (const role of LLM_ROLES) assert.equal(customOpenAIUrl(form, role), 'https://changed.example/v1')
  assert.equal(form.complex_model, 'story')
  assert.equal(form.complex_model_provider, 'custom_openai')
})

test('concurrent discovery at one URL is deduplicated and other URLs keep separate models', async () => {
  let finish
  const calls = []
  const cache = createEndpointModelCache(url => {
    calls.push(url)
    return url.endsWith('/one') ? new Promise(resolve => { finish = resolve }) : Promise.resolve(['two-model'])
  })
  const first = cache.load('https://api.example/one/')
  const duplicate = cache.load('https://api.example/one')
  await cache.load('https://api.example/two')
  finish(['one-model'])
  await Promise.all([first, duplicate])
  assert.deepEqual(calls.sort(), ['https://api.example/one', 'https://api.example/two'])
  assert.deepEqual(cache.models.value['https://api.example/one'], ['one-model'])
  assert.deepEqual(cache.models.value['https://api.example/two'], ['two-model'])
})

test('empty and failed servers never borrow a different endpoint’s model list', async () => {
  const cache = createEndpointModelCache(async url => {
    if (url.endsWith('/failed')) throw new Error('unavailable')
    return url.endsWith('/empty') ? [] : ['good-model']
  })
  await cache.load('https://api.example/good')
  assert.deepEqual(await cache.load('https://api.example/empty'), [])
  await assert.rejects(cache.load('https://api.example/failed'))
  assert.deepEqual(cache.models.value['https://api.example/failed'], [])
  assert.deepEqual(cache.models.value['https://api.example/good'], ['good-model'])
  assert.equal(cache.loading.value['https://api.example/failed'], false)
})
