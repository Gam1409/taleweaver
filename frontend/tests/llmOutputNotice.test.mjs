import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'

const source = readFileSync(new URL('../src/components/admin/LlmOutputNotice.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const compiled = compileScript(descriptor, { id: 'output-notice', inlineTemplate: true }).content
  .replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
const code = ts.transpileModule(compiled, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
const Notice = (await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default
const render = props => renderToString(createSSRApp({ render: () => h(Notice, props) }))

test('legacy prompt and JSON-only connections describe their actual limits', async () => {
  const prompt = await render({ provider: 'custom_openai' })
  assert.match(prompt, /Prompt-only output/)
  assert.match(prompt, /checks the complete response locally/)
  const json = await render({ provider: 'custom_openai', responseFormat: 'json_object' })
  assert.match(json, /JSON-only output/)
  assert.match(json, /Valid JSON can still contain an invalid decision/)
  assert.doesNotMatch(json, /Prompt-only output:/)
})

test('native and cloud connections do not promise universal schema enforcement', async () => {
  for (const provider of ['ollama', 'openai', 'anthropic', 'google', 'deepseek', 'openrouter', 'custom_openai']) {
    const html = await render({ provider, responseFormat: 'json_schema' })
    assert.match(html, /depends on the provider, model and server version/)
    assert.match(html, /does not certify every task schema/)
    assert.match(html, /role="note"/)
  }
})

test('notice belongs to connection settings outside collapsed generation options', () => {
  const parent = readFileSync(new URL('../src/components/admin/RoleGenerationSettings.vue', import.meta.url), 'utf8')
  assert.ok(parent.indexOf('<LlmOutputNotice') < parent.indexOf('<details'))
  assert.doesNotMatch(source, /notificationService|useNotifications|emit\(/)
})
