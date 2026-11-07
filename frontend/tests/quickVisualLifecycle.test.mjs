import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ref } from 'vue'
import ts from 'typescript'

const source = readFileSync(new URL('../src/views/AdventureEditorView.vue', import.meta.url), 'utf8')
const quick = source.slice(source.indexOf('async function quickRegenerateVisual('), source.indexOf('function requestRegenerateAll('))
const batch = source.slice(source.indexOf('async function regenerateAll('), source.indexOf('function cancelRegeneration('))
const code = ts.transpileModule(`return function fixture(ref, visualService, console) {
 const props={adventureId:'adventure'}, isQuickGenerating=ref({}), activeAbortControllers=ref(new Map());
 const isBatchGenerating=ref({}), debugData=ref({}), editorScenes=ref([{id:'A'},{id:'B'}]);
 const editorNpcs=ref([]),editorObjects=ref([]),editorContainers=ref([]),editorSwitches=ref([]),editorTextLogs=ref([]);
 const notices=[], refreshes=[];
 const addNotification=(...args)=>notices.push(args),fetchDebugInfo=async()=>refreshes.push(true);
 const getRegenerateKindLabel=()=> 'locations',isImageMissingForRegeneration=()=>true;
 ${quick}
 ${batch}
 return {quickRegenerateVisual,regenerateAll,isQuickGenerating,activeAbortControllers,isBatchGenerating,notices,refreshes};
}`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
const setup = new Function(code)()
const fixture = generate => setup(ref, { quickRegenerateVisual: generate }, { log() {}, error() {} })

test('a failed quick image request reports failure instead of resolving as success', async () => {
  const f = fixture(async () => { throw new Error('Image provider unavailable.') })
  assert.equal(await f.quickRegenerateVisual('scene', 'A'), false)
  assert.deepEqual(f.notices, [['Image provider unavailable.', 'error']])
  assert.equal(f.refreshes.length, 0)
  assert.equal(f.isQuickGenerating.value.scene_A, false)
})

test('batch image generation counts provider errors as failures', async () => {
  const f = fixture(async (_adventure, _kind, id) => {
    if (id === 'A') throw new Error('First image failed.')
  })
  await f.regenerateAll('scene')
  assert.deepEqual(f.notices.at(-1), ['Generated 1 locations image(s), 1 failed.', 'error'])
  assert.equal(f.isBatchGenerating.value.scene, false)
})

test('an older quick image request cannot clear the newer request for the same asset', async () => {
  const pending = []
  const f = fixture((...args) => new Promise(resolve => pending.push({ args, resolve })))
  const old = f.quickRegenerateVisual('scene', 'A')
  const current = f.quickRegenerateVisual('scene', 'A')
  assert.equal(pending[0].args.at(-1).aborted, true)
  pending[0].resolve()
  await old
  assert.equal(f.isQuickGenerating.value.scene_A, true)
  assert.equal(f.activeAbortControllers.value.get('scene_A').signal, pending[1].args.at(-1))
  assert.equal(f.refreshes.length, 0)
  pending[1].resolve()
  assert.equal(await current, true)
  assert.equal(f.isQuickGenerating.value.scene_A, false)
  assert.equal(f.activeAbortControllers.value.size, 0)
  assert.equal(f.refreshes.length, 1)
})
