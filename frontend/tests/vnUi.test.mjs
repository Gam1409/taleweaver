import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import { effectScope, nextTick, reactive } from 'vue'
import ts from 'typescript'

const tick = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)) }
const reply = data => new Response(JSON.stringify(data))
let sequence = 0
async function fixture(t, component, props, exports, request, job = async () => ({})) {
  const key = `__vnUiTest${sequence++}`
  globalThis[key] = { props: reactive(props), request, job }
  t.after(() => { delete globalThis[key] })
  let source = readFileSync(new URL(`../src/components/game/${component}.vue`, import.meta.url), 'utf8')
    .match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  source = source.replace(/import[\s\S]*?from ['"][^'"]+['"];?/g, '')
  source = source.replace(/const props = defineProps<[\s\S]*?>\(\);?/, `const props = globalThis['${key}'].props`)
    .replace(/const emit = defineEmits<[\s\S]*?>\(\);?/, 'const emit = () => {}')
    .replace(/defineExpose\([\s\S]*?\);?/, '')
  source = `import {computed, ref, watch, onScopeDispose as onBeforeUnmount} from '${import.meta.resolve('vue')}';
const window = globalThis;
const onMounted = () => {};
const useDialogFocus = () => {};
const apiFetch = (...args) => globalThis['${key}'].request(...args);
const runVisualJob = (...args) => globalThis['${key}'].job(...args);
const getOriginalImageUrl = path => path;
export function setup() { ${source}; return { ${exports} }; }`
  const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  const module = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
  const scope = effectScope()
  const state = scope.run(module.setup)
  t.after(() => scope.stop())
  return { ...state, props: globalThis[key].props, scope }
}

test('VN pace loads persisted choice and generic Save sends only edited pace', async t => {
  const calls = []
  const f = await fixture(t, 'VnNarrationSettings', { sessionId: 'session-a' }, 'pace, save, loaded, error', async (url, options) => {
    calls.push({ url, options })
    return reply({ settings: { pace: 'leisurely' } })
  })
  await tick()
  assert.equal(f.pace.value, 'leisurely')
  assert.equal(await f.save(), true)
  assert.equal(calls.length, 1)
  f.pace.value = 'brisk'
  assert.equal(await f.save(), true)
  assert.equal(calls[1].options.method, 'PATCH')
  assert.deepEqual(JSON.parse(calls[1].options.body), { pace: 'brisk', scene_staging: false, visual_audit: true, visual_audit_failure: 'block' })
})

test('a failed pace load does not overwrite settings or block unrelated Save', async t => {
  let calls = 0
  const f = await fixture(t, 'VnNarrationSettings', { sessionId: 'session-a' }, 'save, error', async () => { calls++; return new Response('', { status: 500 }) })
  await tick()
  assert.match(f.error.value, /Could not load/)
  assert.equal(await f.save(), true)
  assert.equal(calls, 1)
})

test('pace save failure stays visible and prevents closing with an unsaved change', async t => {
  const f = await fixture(t, 'VnNarrationSettings', { sessionId: 'session-a' }, 'pace, save, error', async (_url, options) => options.method === 'PATCH' ? new Response('', { status: 500 }) : reply({ settings: { pace: 'balanced' } }))
  await tick()
  f.pace.value = 'brisk'
  assert.equal(await f.save(), false)
  assert.match(f.error.value, /Could not save/)
})

test('illustration targets the persisted reply and never requests generation on load', async t => {
  const jobs = [], urls = []
  const f = await fixture(t, 'VnMomentIllustration', { sessionId: 's-a', messageId: 'm-a', canGenerate: true }, 'generate, imageUrl, state', async url => { urls.push(url); return reply({ available: true, reason: null, image_url: null }) }, async (...args) => { jobs.push(args); return { image_url: '/saved/m-a.png' } })
  await tick()
  assert.equal(jobs.length, 0)
  assert.equal(urls[0], '/adventures/s-a/illustrations?message_id=m-a')
  await f.generate()
  assert.equal(jobs[0][0], 'session_illustration')
  assert.deepEqual(jobs[0][1], { message_id: 'm-a' })
  assert.equal(jobs[0][4], 's-a')
  assert.equal(f.imageUrl.value, '/saved/m-a.png')
})

test('older replies without a snapshot cannot silently render the current scene', async t => {
  let jobs = 0
  const f = await fixture(t, 'VnMomentIllustration', { sessionId: 's-a', messageId: 'old', canGenerate: true }, 'generate, state', async () => reply({ available: false, reason: 'No historical snapshot', image_url: null }), async () => { jobs++; return {} })
  await tick()
  await f.generate()
  assert.equal(jobs, 0)
  assert.equal(f.state.value.reason, 'No historical snapshot')
})

test('switching sessions aborts and ignores stale illustration responses', async t => {
  const pending = []
  const f = await fixture(t, 'VnMomentIllustration', { sessionId: 's-a', messageId: 'm-a', canGenerate: true }, 'state', (url, options) => new Promise(resolve => pending.push({ url, signal: options.signal, resolve })))
  f.props.sessionId = 's-b'
  await tick()
  assert.equal(pending[0].signal.aborted, true)
  pending[0].resolve(reply({ available: true, image_url: '/wrong.png' }))
  await tick()
  assert.equal(f.state.value, null)
  pending[1].resolve(reply({ available: true, image_url: '/right.png' }))
  await tick()
  assert.equal(f.state.value.image_url, '/right.png')
})


test('busy session explains why pace cannot save and retains the edited choice for retry', async t => {
  let busy = true
  const f = await fixture(t, 'VnNarrationSettings', { sessionId: 'session-a' }, 'pace, save, error', async (_url, options) => {
    if (options.method !== 'PATCH') return reply({ settings: { pace: 'balanced' } })
    return busy ? new Response(JSON.stringify({ detail: 'Wait for the current turn to finish.' }), { status: 409 }) : reply({ settings: { pace: 'brisk' } })
  })
  await tick()
  f.pace.value = 'brisk'
  assert.equal(await f.save(), false)
  assert.equal(f.error.value, 'Wait for the current turn to finish.')
  assert.equal(f.pace.value, 'brisk')
  busy = false
  assert.equal(await f.save(), true)
  assert.equal(f.error.value, '')
})

test('a malformed busy response still gives a useful retry instruction', async t => {
  const f = await fixture(t, 'VnNarrationSettings', { sessionId: 'session-a' }, 'pace, save, error', async (_url, options) => options.method === 'PATCH' ? new Response('<html>Proxy error</html>', { status: 409 }) : reply({ settings: { pace: 'balanced' } }))
  await tick()
  f.pace.value = 'brisk'
  assert.equal(await f.save(), false)
  assert.equal(f.error.value, 'Wait for the current reply to finish, then save again.')
})


test('generic settings Save stops before other writes when VN pace is busy', async t => {
  const calls = []
  const f = await fixture(t, 'SessionSettingsModal', { sessionId: 's-a', mode: 'vn', isSaving: false }, 'vnNarration, exploration, saveAll', async () => reply({}))
  f.vnNarration.value = { save: async () => { calls.push('pace'); return false } }
  f.exploration.value = { save: async () => { calls.push('exploration'); return true } }
  await f.saveAll()
  assert.deepEqual(calls, ['pace'])
})

test('scene staging toggle saves independently of narration pace', async t => {
  const calls = []
  const f = await fixture(t, 'VnNarrationSettings', { sessionId: 'session-a' }, 'sceneStaging, save', async (_url, options) => {
    calls.push(options)
    return reply({ settings: { pace: 'balanced', scene_staging: false } })
  })
  await tick()
  f.sceneStaging.value = true
  assert.equal(await f.save(), true)
  assert.deepEqual(JSON.parse(calls[1].body), { pace: 'balanced', scene_staging: true, visual_audit: true, visual_audit_failure: 'block' })
  assert.equal(await f.save(), true)
  assert.equal(calls.length, 2)
})


test('visual preparation loads persisted choices and saves them without changing narration settings', async t => {
  const calls = []
  const f = await fixture(t, 'VnNarrationSettings', { sessionId: 'session-a' }, 'visualAudit, auditFailure, save', async (_url, options) => {
    calls.push(options)
    return reply({ settings: { pace: 'leisurely', scene_staging: true, visual_audit: true, visual_audit_failure: 'block' } })
  })
  await tick()
  assert.equal(f.visualAudit.value, true)
  f.auditFailure.value = 'warn'
  assert.equal(await f.save(), true)
  assert.deepEqual(JSON.parse(calls[1].body), {
    pace: 'leisurely', scene_staging: true, visual_audit: true, visual_audit_failure: 'warn',
  })
  assert.equal(await f.save(), true)
  assert.equal(calls.length, 2)
})

test('older settings keep audit defaults without exposing a legacy mode', async t => {
  const calls = []
  const f = await fixture(t, 'VnNarrationSettings', { sessionId: 'session-a' }, 'visualAudit, auditFailure, save', async (_url, options) => {
    calls.push(options)
    return reply({ settings: { pace: 'balanced' } })
  })
  await tick()
  assert.equal(f.visualAudit.value, true)
  assert.equal(f.auditFailure.value, 'block')
  assert.equal(await f.save(), true)
  assert.equal(calls.length, 1)
  f.visualAudit.value = false
  assert.equal(await f.save(), true)
  assert.equal(JSON.parse(calls[1].body).visual_preparation, undefined)
})

test('visual plans expose limits and explicitly request a rebuild', async t => {
  const jobs = []
  const f = await fixture(t, 'VnMomentIllustration', { sessionId: 's-a', messageId: 'm-a', canGenerate: true }, 'generate, state, planNotice', async () => reply({ available: true, plan_enabled: true, image_url: null }), async (...args) => {
    jobs.push(args)
    return { image_url: '/saved/plan.png', generation_details: { visual_plan: { limited_output_coverage: true, semantic_audit: 'not_run' } } }
  })
  await tick()
  await f.generate(true)
  assert.equal(jobs[0][1].refresh_plan, true)
  assert.match(f.planNotice.value, /limited expression/)
  assert.match(f.planNotice.value, /not been verified/)
})

test('visual fact diagnostics slice actual prompt by Unicode code points', async t => {
  const f = await fixture(t, 'VisualPlanDetails', {
    positive: '✨ A person.',
    plan: { normalization_cache_hit: true, provenance: { facts: [
      { predicate: 'present', start: 0, positive_start: 2, positive_end: 11 },
      { predicate: 'placement', start: null, positive_start: null, positive_end: null, disposition: 'tag_binding' },
    ] } },
  }, 'facts, represented, reused', async () => reply({}))
  assert.equal(f.facts.value[0].excerpt, 'A person.')
  assert.equal(f.facts.value[1].excerpt, '')
  assert.equal(f.facts.value[1].disposition, 'tag_binding')
  assert.equal(f.represented.value, 1)
  assert.equal(f.reused.value, true)
})

test('visual fact diagnostics do not guess unavailable final-text offsets', async t => {
  const f = await fixture(t, 'VisualPlanDetails', {
    positive: 'Text', plan: { provenance: { facts: [
      { predicate: 'present', start: 0, positive_start: 8, positive_end: 12 },
      { predicate: 'posture', start: 0, positive_start: 1, positive_end: 0 },
    ] } },
  }, 'facts', async () => reply({}))
  assert.ok(f.facts.value.every(fact => fact.excerpt === ''))
})
