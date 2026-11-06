import { test } from 'node:test'
import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFileSync } from 'node:fs'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'

const source = readFileSync(
  new URL('../src/components/game/SessionLoadError.vue', import.meta.url),
  'utf8'
)
const { descriptor } = parse(source)
const compiled = ts
  .transpileModule(
    compileScript(descriptor, { id: 'session-load-error', inlineTemplate: true }).content,
    {
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
    }
  )
  .outputText.replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
const component = (
  await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
).default

test('session load error offers retry and library navigation and escapes its message', async () => {
  const html = await renderToString(
    createSSRApp({ render: () => h(component, { message: '<script>private</script>' }) })
  )
  assert.match(html, /role="alertdialog"/)
  assert.match(html, /Try again/)
  assert.match(html, /Back to library/)
  assert.match(html, /&lt;script&gt;/)
  assert.doesNotMatch(html, /<script>/)
})
