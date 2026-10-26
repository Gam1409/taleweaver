import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { Buffer } from 'node:buffer'
import { parse, compileScript } from '@vue/compiler-sfc'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const vueUrl = pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href
const filename = new URL('../src/components/editor/ClothingDetailSettings.vue', import.meta.url)
const { descriptor } = parse(readFileSync(filename, 'utf8'), { filename: filename.pathname })
const compiled = compileScript(descriptor, { id: 'clothing-settings-test', inlineTemplate: true })
const source = ts
  .transpileModule(compiled.content, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 }
  })
  .outputText.replace(/from ['"]vue['"]/g, `from '${vueUrl}'`)
const { default: Settings } = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
)
const render = props => renderToString(createSSRApp({ render: () => h(Settings, props) }))

test('saved existing preference is visible, checked and not redundantly submitted', async () => {
  const html = await render({ modelValue: true, savedValue: true, isSaving: false })
  assert.match(html, /type="checkbox" checked/)
  assert.match(html, /<button[^>]* disabled(?=[ >])/)
  assert.match(html, />Enabled<\/span>/)
  assert.match(html, /existing saved sessions keep their settings/)
})

test('both enabling and disabling expose an actionable unsaved change', async () => {
  for (const enabled of [true, false]) {
    const html = await render({ modelValue: enabled, savedValue: !enabled, isSaving: false })
    assert.match(html, /Unsaved changes/)
    assert.doesNotMatch(html, /<button[^>]* disabled(?=[ >])/)
    assert.match(html, /Save clothing settings/)
  }
})

test('conversion in progress blocks further toggles and duplicate saves', async () => {
  const html = await render({ modelValue: true, savedValue: false, isSaving: true })
  assert.match(html, /<input[^>]* disabled(?=[ >])/)
  assert.match(html, /<button[^>]* disabled(?=[ >])/)
  assert.match(html, /Preparing character details/)
})
