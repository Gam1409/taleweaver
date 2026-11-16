import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { reactive, ref } from 'vue'
import ts from 'typescript'

const source = readFileSync(new URL('../src/views/AdventureEditorView.vue', import.meta.url), 'utf8')
const body = source.slice(source.indexOf('async function fetchDebugInfo()'), source.indexOf('async function setStartScene('))
const code = ts.transpileModule(`return function setup(ref,reactive,adventureService) {
 const props=reactive({adventureId:'A'}),debugData=ref(null),visualsCacheVersion=ref(0),errorMsg=ref('');
 let debugInfoRevision=0;
 ${body}
 return {props,debugData,visualsCacheVersion,errorMsg,fetchDebugInfo};
}`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
const setup = new Function('console', code)({ error() {} })

function fixture() {
  const pending = []
  const state = setup(ref, reactive, {
    fetchDebugInfo: id => new Promise((resolve, reject) => pending.push({ id, resolve, reject })),
    normalizeDebugPayload: value => value,
  })
  return { ...state, pending }
}

test('late world assets cannot replace assets belonging to the newly selected adventure', async () => {
  const f = fixture()
  const old = f.fetchDebugInfo()
  f.props.adventureId = 'B'
  const current = f.fetchDebugInfo()
  f.pending[1].resolve({ adventure: 'B' })
  await current
  f.pending[0].resolve({ adventure: 'A' })
  await old
  assert.deepEqual(f.debugData.value, { adventure: 'B' })
  assert.equal(f.visualsCacheVersion.value, 1)
})

test('an older failed refresh cannot erase a newer successful asset refresh', async () => {
  const f = fixture()
  const old = f.fetchDebugInfo()
  const current = f.fetchDebugInfo()
  f.pending[1].resolve({ image_url: '/latest.png' })
  await current
  f.pending[0].reject(new Error('Old refresh timed out.'))
  await old
  assert.deepEqual(f.debugData.value, { image_url: '/latest.png' })
  assert.equal(f.errorMsg.value, '')
})
