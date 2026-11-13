import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
import { displayModule, job, source, state } from './worldInfoModule.mjs'
const { descriptor } = parse(readFileSync(new URL('../src/components/game/world-info/WorldInfoFiles.vue', import.meta.url), 'utf8'))
const compiled = ts.transpileModule(compileScript(descriptor, { id: 'world-info-processing-test', inlineTemplate: true }).content, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  .replaceAll("from 'vue'", `from '${import.meta.resolve('vue')}'`).replaceAll('from "vue"', `from '${import.meta.resolve('vue')}'`)
  .replace(/import \{[^}]+\} from ['"]lucide-vue-next['"];?/, 'const FileText = { render: () => null }, Upload = { render: () => null };')
  .replace("from '@/services/worldInfoDisplay'", `from '${displayModule}'`)
const Files = (await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)).default
async function render(overrides = {}, limits = {}) {
  const current = { ...job, request_limit: 8, ...overrides }, overview = state()
  Object.assign(overview.limits, { max_entries: 10000, max_facts: 80000, max_session_entry_bytes: 32 * 1024 * 1024 }, limits)
  const currentSource = { ...source, job: current }
  const controller = { data: { state: overview, job: current, source: { source: currentSource, revisions: [current] }, busy: '', mobileDetail: true } }
  return renderToString(createSSRApp({ render: () => h(Files, { controller }) }))
}
test('source limits distinguish count quotas, canonical evidence storage and searchable text sizes', async () => {
  const html = await render()
  assert.match(html, /10,000 entries/)
  assert.match(html, /80,000 facts/)
  assert.match(html, /32 MiB/)
  assert.match(html, /including evidence/)
  assert.match(html, /whichever limit is reached first/)
  assert.match(html, /Searchable text sizes.*do not include all saved entry data/)
  assert.match(await render({}, { max_entries: 5000, max_facts: 40000, max_session_entry_bytes: 64 * 1024 * 1024 }), /5,000 entries.*40,000 facts.*64 MiB/)
  assert.match(await render({}, { max_entries: undefined, max_facts: undefined, max_session_entry_bytes: undefined }), /10,000 entries.*80,000 facts.*32 MiB/)
})
test('workload distinguishes a normal remaining run from the revision lifetime logical-request budget', async () => {
  const html = await render({ total_batches: 24, cursor: 4, attempts: 9, request_limit: 96, can_resume: true })
  assert.match(html, /9 \/ 96 logical model requests used/)
  assert.match(html, /87 remaining in this source version/)
  assert.match(html, /Normal remaining workload: up to 40 logical model requests/)
  assert.match(html, /Provider SDK retries are excluded/)
  assert.match(html, /starts, resumes and corrections/)
})
test('exhaustion explains saved work and unchanged-source dedup even when the last error was invalid output', async () => {
  for (const last_error_code of ['request_limit', 'invalid_output']) {
    const html = await render({ total_batches: 2, cursor: 1, attempts: 8, request_limit: 8, last_error_code, can_resume: false, can_start: false })
    assert.match(html, /Analysis stopped.*lifetime request limit/)
    assert.match(html, /Saved source text, entries and processing progress are kept/)
    assert.match(html, /corrected source.*changed version/)
    assert.match(html, /unchanged content.*does not reset/)
    assert.doesNotMatch(html, />Resume processing<|resume when available/)
  }
})
test('legacy over-limit records remain readable, unknown limits preserve server controls, and final-cap success is not a failure', async () => {
  assert.match(await render({ attempts: 12, request_limit: 8, cursor: 1, total_batches: 2, can_resume: false }), /0 remaining in this source version/)
  const unknown = await render({ attempts: 3, request_limit: null, total_batches: 0, cursor: 0, can_start: true })
  assert.match(unknown, /3 logical model requests used/)
  assert.match(unknown, /Lifetime request limit will be determined when analysis starts/)
  assert.match(unknown, />Analyse source</)
  assert.match(await render({ request_limit: undefined }), /Lifetime request limit will be determined when analysis starts/)
  for (const status of ['queued', 'processing']) {
    const inFlight = await render({ attempts: 8, request_limit: 8, cursor: 1, total_batches: 2, status, last_error_code: null, can_resume: false, can_cancel: true })
    assert.doesNotMatch(inFlight, /Analysis stopped/)
    assert.match(inFlight, />Cancel processing</)
  }
  const complete = await render({ attempts: 8, request_limit: 8, cursor: 2, total_batches: 2, status: 'review', last_error_code: null })
  assert.doesNotMatch(complete, /Analysis stopped/)
})
