import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import ts from 'typescript'

let sequence = 0
async function fixture(t, api) {
  const key = `__generationResume${sequence++}`
  const events = []
  globalThis[key] = { api, events }
  t.after(() => { delete globalThis[key] })
  let source = readFileSync(new URL('../src/components/portal/GenerationProgressModal.vue', import.meta.url), 'utf8')
    .match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  source = source.replace(/import[\s\S]*?from ['"][^'"]+['"];?/g, '')
    .replace(/const props = defineProps<[\s\S]*?>\(\)/, "const props = {adventureId: 'saved-world', adventureTitle: 'Saved world'}")
    .replace(/const emit = defineEmits<[\s\S]*?>\(\)/, `const emit = event => globalThis['${key}'].events.push(event)`)
  source = `import {ref, computed, nextTick} from '${import.meta.resolve('vue')}';
const api = globalThis['${key}'].api;
const GENERATION_SAYINGS = ['Preparing'];
const onMounted = () => {};
const onUnmounted = () => {};
const window = {setInterval: () => 1};
const clearInterval = () => {};
${source}
export {checkStatus, resumeGeneration, hasError, canResume, completedStages, resumeError, statusDescription, isResuming};`
  const compiled = ts.transpileModule(source, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext}}).outputText
  return {...await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`), events}
}

test('failed generation exposes saved progress and can resume', async t => {
  const f = await fixture(t, {
    getAdventureStatus: async () => ({status: 'Failed', is_ready: false, error: 'Timed out', can_resume: true, completed_stages: 3})
  })
  await f.checkStatus()
  assert.equal(f.hasError.value, true)
  assert.equal(f.canResume.value, true)
  assert.equal(f.completedStages.value, 3)
})

test('resume uses the same adventure and restarts progress monitoring', async t => {
  const calls = []
  const f = await fixture(t, {
    resumeAdventureGeneration: async id => {calls.push(id)},
    getAdventureGenerationLogs: async () => ({logs: []}),
    getAdventureStatus: async () => ({status: 'Characters 2/4', is_ready: false, can_resume: false, completed_stages: 3})
  })
  f.hasError.value = true
  await f.resumeGeneration()
  assert.deepEqual(calls, ['saved-world'])
  assert.deepEqual(f.events, ['resumed'])
  assert.equal(f.hasError.value, false)
  assert.equal(f.statusDescription.value, 'Characters 2/4')
  assert.equal(f.isResuming.value, false)
})

test('failed resume remains visible and duplicate clicks do not create requests', async t => {
  let reject, count = 0
  const pending = new Promise((_, fail) => {reject = fail})
  const f = await fixture(t, {resumeAdventureGeneration: () => {count++; return pending}})
  f.hasError.value = true
  const first = f.resumeGeneration()
  await f.resumeGeneration()
  assert.equal(count, 1)
  reject(new Error('Generation is already resuming.'))
  await first
  assert.match(f.resumeError.value, /already resuming/)
  assert.equal(f.hasError.value, true)
  assert.equal(f.isResuming.value, false)
  assert.deepEqual(f.events, [])
})
