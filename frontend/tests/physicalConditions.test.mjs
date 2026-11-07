import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'

const file = new URL('../src/components/game/DebugPhysicalConditions.vue', import.meta.url)
const { descriptor } = parse(readFileSync(file, 'utf8'))
const source = compileScript(descriptor, { id: 'physical-conditions', inlineTemplate: true }).content
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText.replaceAll('from "vue"', `from '${import.meta.resolve('vue')}'`)
  .replaceAll("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replace("from 'lucide-vue-next'", `from '${import.meta.resolve('lucide-vue-next')}'`)
const { default: Component } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
const render = data => renderToString(createSSRApp({ render: () => h(Component, { data, busy: false }) }))
const sourceQuote = { kind: 'narration', message_id: 'reply', quote: '<script>not executable</script>' }
const row = { id: 'C1', target_id: 'RIN', kind: 'injury', part: 'neck', detail: 'Bandaged wound.', status: 'treated', visibility: 'private', latest: sourceQuote, origin: sourceQuote }
const ledger = { revision: 3, conditions: { C1: row, C2: { ...row, id: 'C2', detail: 'Already healed.', status: 'resolved' } }, subjects: [{ id: 'RIN', name: 'Rin' }], last_check: {}, archived_resolved: 0, archived_events: 0 }

test('state inspector distinguishes retained treatment, resolved records and manual edits', async () => {
  const html = await render(ledger)
  assert.match(html, /Bandaged wound/)
  assert.match(html, /injury · treated · private/)
  assert.doesNotMatch(html, /Already healed/)
  assert.match(html, /No model call or time advance/)
  assert.match(html, /Active conditions are never evicted/)
  assert.doesNotMatch(html, /<script>/)
  assert.match(html, /&lt;script&gt;/)
})

test('missing or invalid ledger is explicit and cannot offer an active save form', async () => {
  for (const data of [undefined, { error: 'Saved state is invalid.' }]) {
    const html = await render(data)
    assert.match(html, /unavailable|invalid/)
    assert.doesNotMatch(html, /<form/)
  }
})

test('rejected candidates are visible without hiding accepted physical facts', async () => {
  const html = await render({ ...ledger, last_check: { status: 'needs_review', rejected: ['Unknown subject.'] } })
  assert.match(html, /Unknown subject/)
  assert.match(html, /Bandaged wound/)
  assert.match(html, /Existing conditions were kept/)
})
