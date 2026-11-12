import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'

function transpile(source) {
  return ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
}
const roles = transpile(readFileSync(new URL('../src/services/llmRoleEndpoints.ts', import.meta.url), 'utf8'))
const rolesUrl = `data:text/javascript;base64,${Buffer.from(roles).toString('base64')}`
const source = readFileSync(new URL('../src/services/llmParallel.ts', import.meta.url), 'utf8')
const code = transpile(source).replace(/from ['"]\.\/llmRoleEndpoints['"]/g, `from '${rolesUrl}'`)
const { normalizeParallel, roleParallel, updateParallel, parallelForSave } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)

test('legacy configuration stays unconfigured until a role is explicitly changed', () => {
  const legacy = normalizeParallel()
  assert.deepEqual(legacy, { roles: {} })
  assert.deepEqual(roleParallel(legacy, 'complex'), { enabled: false, max_concurrent: 2 })
})

test('roles retain independent capacity across disable, enable and saved reload', () => {
  const saved = { roles: { small: { enabled: true, max_concurrent: 3 } } }
  let draft = updateParallel(normalizeParallel(saved), 'complex', { enabled: true })
  draft = updateParallel(draft, 'complex', { max_concurrent: 4 })
  draft = updateParallel(draft, 'complex', { enabled: false })
  assert.equal(roleParallel(draft, 'complex').max_concurrent, 4)
  draft = updateParallel(draft, 'complex', { enabled: true })
  assert.deepEqual(normalizeParallel(JSON.parse(JSON.stringify(draft))), draft)
  assert.deepEqual(roleParallel(draft, 'small'), { enabled: true, max_concurrent: 3 })
  assert.deepEqual(saved, { roles: { small: { enabled: true, max_concurrent: 3 } } })
})

test('saving untouched unchecked controls establishes exclusive policies for every connection', () => {
  const legacy = normalizeParallel()
  const saved = parallelForSave(legacy)
  assert.deepEqual(Object.keys(saved.roles).sort(), ['complex', 'compression', 'generator', 'play_agent', 'small'])
  assert.ok(Object.values(saved.roles).every(policy => policy.enabled === false))
  assert.deepEqual(legacy, { roles: {} })
  const partial = { roles: { small: { enabled: true, max_concurrent: 3 } } }
  assert.deepEqual(parallelForSave(partial).roles.small, partial.roles.small)
  assert.equal(parallelForSave(partial).roles.complex.enabled, false)
  const cards = readFileSync(new URL('../src/components/admin/IntelligenceSection.vue', import.meta.url), 'utf8')
  assert.match(cards, /parallel_requests: parallelForSave\(localForm\.value\.parallel_requests\)/)
})

test('each connection keeps its bounded parallel control inside general settings', () => {
  const file = readFileSync(new URL('../src/components/admin/RoleParallelSettings.vue', import.meta.url), 'utf8')
  const { descriptor, errors } = parse(file)
  assert.deepEqual(errors, [])
  const script = compileScript(descriptor, { id: 'parallel-settings' })
  const template = compileTemplate({ source: descriptor.template.content, filename: 'RoleParallelSettings.vue', id: 'parallel-settings', compilerOptions: { bindingMetadata: script.bindings } })
  assert.deepEqual(template.errors, [])
  assert.match(file, /Allow parallel requests/)
  assert.match(file, /\[2, 3, 4\]/)
  assert.match(file, /:for="`parallel-\$\{role\}`"/)
  assert.match(file, /world changes are applied sequentially/)
  const parent = readFileSync(new URL('../src/components/admin/RoleGenerationSettings.vue', import.meta.url), 'utf8')
  assert.match(parent, /<details[^>]*:data-general-role="role"[\s\S]*?<summary[^>]*>General settings<\/summary>[\s\S]*?<RoleParallelSettings[\s\S]*?<\/details>/)
  assert.equal((parent.match(/<details\b/g) || []).length, 1)
  assert.doesNotMatch(parent, />Generation settings<\/summary>/)
  const cards = readFileSync(new URL('../src/components/admin/IntelligenceSection.vue', import.meta.url), 'utf8')
  assert.equal(cards.match(/<RoleGenerationSettings\s/g).length, 5)
})
