import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createSSRApp, h, ref } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { displayModule, entry, state } from './worldInfoModule.mjs'
import { tagFieldModule } from './worldInfoTagFieldModule.mjs'
const { descriptor } = parse(readFileSync(new URL('../src/components/game/world-info/WorldInfoEntryEditor.vue', import.meta.url), 'utf8'))
const source = compileScript(descriptor, { id: 'world-info-entry-test', inlineTemplate: true }).content
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  .replaceAll("from 'vue'", `from '${import.meta.resolve('vue')}'`).replaceAll('from "vue"', `from '${import.meta.resolve('vue')}'`)
  .replace(/import WorldInfoRelations from .*?;/, 'const WorldInfoRelations = { render: () => null };')
  .replace("from './WorldInfoTagField.vue'", `from '${tagFieldModule}'`)
  .replace("from '@/services/worldInfoDisplay'", `from '${displayModule}'`)
const Editor = (await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)).default
const readerDescriptor = parse(readFileSync(new URL('../src/components/game/world-info/WorldInfoEntryView.vue', import.meta.url), 'utf8')).descriptor
const readerCode = ts.transpileModule(compileScript(readerDescriptor, { id: 'world-info-reader-test', inlineTemplate: true }).content, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  .replaceAll("from 'vue'", `from '${import.meta.resolve('vue')}'`).replaceAll('from "vue"', `from '${import.meta.resolve('vue')}'`)
  .replace("from '@/services/worldInfoDisplay'", `from '${displayModule}'`)
const Reader = (await import(`data:text/javascript;base64,${Buffer.from(readerCode).toString('base64')}`)).default
function render(draft, component = Editor) {
  const controller = { data: { draft, state: state(), candidates: [], candidateNext: null, busy: '' }, dirty: ref(false) }
  return renderToString(createSSRApp({ render: () => h(component, { controller }) }))
}
test('missing current recipients and persisted dormant recipients are both visible and removable without exposing IDs', async () => {
  const html = await render({ ...entry, audience: 'restricted', known_by: ['MISSING_PRIVATE_ID', 'MIRA'], unresolved_known_by: ['MIRA'] })
  assert.match(html, /Remove unavailable recipient 1/)
  assert.match(html, /Remove unavailable recipient 2/)
  assert.match(html, /Assign to Mira/)
  assert.doesNotMatch(html, /MISSING_PRIVATE_ID/)
})
test('entry editor respects field limits and preserves escaped original facts and evidence', async () => {
  const text = '<ScRiPt>alert(1)</ScRiPt><img onerror=evil()>'
  const html = await render({ ...entry, facts: [{ ...entry.facts[0], original_text: text, text: 'An author correction.', evidence: [{ ...entry.facts[0].evidence[0], quote: text }] }] })
  assert.match(html, /maxlength="160"/)
  assert.match(html, /maxlength="500"/)
  assert.match(html, /Author correction/)
  assert.match(html, /&lt;ScRiPt&gt;/)
  assert.doesNotMatch(html, /<script\b|<img\b/i)
})
test('narrator-only reference does not imply learned character knowledge', async () => {
  const html = await render(entry)
  assert.match(html, /does not automatically become a character/)
  assert.match(html, /Current game state takes precedence/)
  assert.match(html, /value="world_fact"[^>]*>World fact/)
  assert.match(html, /value="rumor"[^>]*>Rumor/)
  assert.match(html, /value="news"[^>]*>News/)
  assert.match(html, /Recollection \/ character knowledge/)
  assert.match(html, /Rumors preserve uncertainty/)
  assert.doesNotMatch(html, /Characters who may use this reference|Assign to Mira/)
})
test('entry reader shows escaped summaries, facts, provenance, recipients and versions without edit controls', async () => {
  const text = '<ScRiPt>example()</ScRiPt><img onerror=example()>'
  const html = await render({ ...entry, summary: text, group_name: 'Coastal history', audience: 'restricted', known_by: ['MIRA', 'REMOVED'], unresolved_known_by: ['REMOVED'], facts: [{ ...entry.facts[0], text, original_text: text, evidence: [{ ...entry.facts[0].evidence[0], quote: text }] }], relations: [{ target_id: 'other-entry', kind: 'supports', note: 'A source-backed connection.' }] }, Reader)
  assert.match(html, /Coastal history|Mira|Unavailable character/)
  assert.match(html, /Source version|Saved entry version|UTF-8 bytes/)
  assert.match(html, /A source-backed connection/)
  assert.match(html, /&lt;ScRiPt&gt;/)
  assert.doesNotMatch(html, /<(?:input|select|textarea|script|img)\b/i)
})
