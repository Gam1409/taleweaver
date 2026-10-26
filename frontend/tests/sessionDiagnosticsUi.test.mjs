import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'

const source = readFileSync(new URL('../src/components/game/immersive/SessionDiagnosticsId.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const compiled = ts.transpileModule(compileScript(descriptor, { id: 'session-debug-id', inlineTemplate: true }).content, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
}).outputText.replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
const component = (await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)).default
const render = props => renderToString(createSSRApp({ render: () => h(component, props) }))
const sessionId = '01a179bd-278e-7539-94dc-4b669f7ac68f'

test('session UUID is small, selectable and only rendered when system diagnostics are enabled', async () => {
  const disabled = await render({ enabled: false, sessionId })
  assert.doesNotMatch(disabled, new RegExp(sessionId))
  const enabled = await render({ enabled: true, sessionId })
  assert.match(enabled, new RegExp(sessionId))
  assert.match(enabled, /text-\[9px\]/)
  assert.match(enabled, /select-text/)
  assert.doesNotMatch(enabled, /button|tooltip|Turn-ID/)
})

test('empty IDs stay hidden and displayed values are escaped', async () => {
  assert.doesNotMatch(await render({ enabled: true }), /Session UUID/)
  const rendered = await render({ enabled: true, sessionId: '<script>bad</script>' })
  assert.doesNotMatch(rendered, /<script>/)
  assert.match(rendered, /&lt;script&gt;/)
})
