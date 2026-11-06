/* eslint-env node, es2020 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import ts from 'typescript'
import { statusPollerModule } from './statusPollerModule.mjs'

let sequence = 0
async function fixture(t, api) {
  const key = `__generationResume${sequence++}`
  const events = []
  globalThis[key] = { api: { getAdventureGenerationLogs: async () => ({logs: []}), ...api }, events }
  t.after(() => { delete globalThis[key] })
  let source = readFileSync(new URL('../src/components/portal/GenerationProgressModal.vue', import.meta.url), 'utf8')
    .match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  source = source.replace(/import[\s\S]*?from ['"][^'"]+['"];?/g, '')
    .replace(/const props = defineProps<[\s\S]*?>\(\)/, "const props = {adventureId: 'saved-world', adventureTitle: 'Saved world'}")
    .replace(/const emit = defineEmits<[\s\S]*?>\(\)/, `const emit = event => globalThis['${key}'].events.push(event)`)
  source = `import {ref, computed, nextTick} from '${import.meta.resolve('vue')}';
import {createStatusPoller} from '${statusPollerModule}';
const api = globalThis['${key}'].api;
const GENERATION_SAYINGS = ['Preparing'];
const onMounted = () => {};
const onUnmounted = () => {};
const window = {setInterval: () => 1};
const clearInterval = () => {};
${source}
const checkStatus = () => poller.checkNow();
export {checkStatus, startPolling, stopPolling, connectionPaused, resumeGeneration, hasError, canResume, completedStages, resumeError, statusDescription, isResuming};`
  const compiled = ts.transpileModule(source, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext}}).outputText
  const result = {...await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`), events}
  t.after(() => result.stopPolling())
  return result
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

test('progress monitoring pauses on connection failures and retries reads without resuming generation', async t => {
  t.mock.timers.enable({apis: ['setTimeout']})
  let calls = 0, available = false
  const f = await fixture(t, {
    getAdventureStatus: async () => {
      calls++
      if (!available) throw new TypeError('Offline')
      return {status: 'Ready', is_ready: true}
    },
    resumeAdventureGeneration: async () => { throw new Error('A status retry must never restart generation') }
  })
  await f.startPolling()
  for (let index = 0; index < 12; index++) {
    t.mock.timers.tick(30_000)
    await new Promise(resolve => setImmediate(resolve))
  }
  assert.equal(calls, 6)
  assert.equal(f.hasError.value, false)
  assert.equal(f.connectionPaused.value, true)
  assert.match(f.statusDescription.value, /may still be running/)
  available = true
  await f.startPolling()
  assert.equal(calls, 7)
  assert.equal(f.connectionPaused.value, false)
  assert.deepEqual(f.events, [])
})
