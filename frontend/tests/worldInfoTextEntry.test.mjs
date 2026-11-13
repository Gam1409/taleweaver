import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { compileScript, parse } from '@vue/compiler-sfc'
import { effectScope, nextTick, ref, shallowReactive } from 'vue'
import ts from 'typescript'
import { controllerModule, displayModule, job, source, state } from './worldInfoModule.mjs'

const { useWorldInfo } = await import(controllerModule)
const { descriptor } = parse(readFileSync(new URL('../src/components/game/world-info/WorldInfoTextEntry.vue', import.meta.url), 'utf8'))
const script = compileScript(descriptor, { id: 'world-info-text-entry-test' }).content
const compiled = ts.transpileModule(script, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  .replaceAll("from 'vue'", `from '${import.meta.resolve('vue')}'`).replaceAll('from "vue"', `from '${import.meta.resolve('vue')}'`)
  .replace(/import \{[^}]+\} from ['"]lucide-vue-next['"];?/, 'const FilePenLine = {}, Sparkles = {};')
  .replace("from '@/services/worldInfoDisplay'", `from '${displayModule}'`)
const TextEntry = (await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)).default
const submitted = { title: 'Eastern pier notes', text: 'A blue lantern marks the eastern pier.\n\nA coastal note. 🧭' }
const reply = value => Response.json(structuredClone(value))
const tick = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)) }
function deferred() {
  let resolve
  const promise = new Promise(finish => { resolve = finish })
  return { promise, resolve }
}
async function fixture(t, { delayRefresh = false, delayUpload = false, failUpload = false } = {}) {
  const refreshStarted = deferred(), refreshResult = deferred(), uploadStarted = deferred(), uploadResult = deferred()
  const calls = [], mutations = []
  let uploaded = false, refreshHeld = false, uploadSignal
  t.mock.method(globalThis, 'fetch', async (path, options = {}) => {
    calls.push(path)
    if (options.method === 'POST') mutations.push({ path, body: options.body })
    if (path.endsWith('/sources') && options.method === 'POST') {
      uploadSignal = options.signal
      uploadStarted.resolve()
      if (delayUpload) return uploadResult.promise
      if (failUpload) return Response.json({}, { status: 503 })
      uploaded = true
      return reply({ source, revision: { ...job, can_start: true }, duplicate: false })
    }
    if (path.endsWith('/process')) return reply({ source, revision: job })
    if (path.endsWith('/sources/source-1')) return reply({ source, revisions: [job] })
    if (path.endsWith('/world-info')) {
      if (delayRefresh && uploaded && !refreshHeld) {
        refreshHeld = true
        refreshStarted.resolve()
        return refreshResult.promise
      }
      return reply(state(decodeURIComponent(path.split('/')[2])))
    }
    throw new Error(`Unexpected mocked World Info path: ${path}`)
  })
  const scope = effectScope(), sid = ref('session/a')
  t.after(() => scope.stop())
  const controller = scope.run(() => useWorldInfo(sid))
  await tick()
  await controller.changeTab('create')
  const props = shallowReactive({ controller, modelValue: structuredClone(submitted) })
  const updates = []
  const setup = scope.run(() => TextEntry.setup(props, {
    expose() {},
    emit(event, value) {
      assert.equal(event, 'update:modelValue')
      updates.push(value)
      props.modelValue = value
    },
  }))
  return {
    controller, sid, props, updates, calls, mutations, analyse: setup.analyse,
    refreshStarted: refreshStarted.promise, uploadStarted: uploadStarted.promise,
    releaseRefresh: () => refreshResult.resolve(reply(state())),
    releaseUpload: () => uploadResult.resolve(reply({ source, revision: { ...job, can_start: true }, duplicate: false })),
    uploadAborted: () => uploadSignal?.aborted,
  }
}

for (const [field, value] of [['text', 'A copper bell hangs above the western gate.'], ['title', 'A later unsaved source title']]) {
  test(`a delayed successful refresh preserves a newer local source ${field} and its current tab`, async t => {
    const f = await fixture(t, { delayRefresh: true })
    const pending = f.analyse()
    await f.refreshStarted
    const newer = { ...submitted, [field]: value }
    f.props.modelValue = newer

    f.releaseRefresh()
    await pending

    assert.deepEqual(f.props.modelValue, newer)
    assert.deepEqual(f.updates, [])
    assert.equal(f.controller.data.tab, 'create')
    assert.equal(f.controller.data.busy, '')
  })
}

test('an unchanged successful submission clears its draft and opens the saved source in Files', async t => {
  const f = await fixture(t, { delayRefresh: true })
  const pending = f.analyse()
  await f.refreshStarted
  assert.deepEqual(f.updates, [])

  f.releaseRefresh()
  await pending

  assert.deepEqual(f.props.modelValue, { title: '', text: '' })
  assert.deepEqual(f.updates, [{ title: '', text: '' }])
  assert.equal(f.controller.data.tab, 'files')
  assert.equal(f.controller.data.mobileDetail, true)
  assert.equal(f.controller.data.source.source.id, source.id)
  assert.equal(f.controller.data.busy, '')
  const upload = f.mutations.find(value => value.path.endsWith('/sources'))
  assert.equal(upload.body.get('title'), submitted.title)
  assert.equal(upload.body.get('file').name, 'written-entry.md')
  assert.equal(await upload.body.get('file').text(), submitted.text)
  assert.equal(f.mutations.filter(value => value.path.endsWith('/process')).length, 1)
  assert.equal(f.mutations.some(value => value.path.endsWith('/publish')), false)
})

test('a failed upload preserves the editable source draft without changing tabs', async t => {
  const f = await fixture(t, { failUpload: true })

  await f.analyse()

  assert.deepEqual(f.props.modelValue, submitted)
  assert.deepEqual(f.updates, [])
  assert.equal(f.controller.data.tab, 'create')
  assert.equal(f.controller.data.busy, '')
  assert.ok(f.controller.data.error)
  assert.equal(f.mutations.some(value => value.path.endsWith('/process')), false)
})

test('an old-session upload completion cannot clear the current session draft or navigate it', async t => {
  const f = await fixture(t, { delayUpload: true })
  const pending = f.analyse()
  await f.uploadStarted
  f.sid.value = 'session-b'
  await tick()
  await f.controller.changeTab('create')
  const current = { title: 'Current session notes', text: 'A brass lamp stands beside the archive door.' }
  f.props.modelValue = current
  const callsBefore = f.calls.length
  assert.equal(f.uploadAborted(), true)

  f.releaseUpload()
  await pending

  assert.deepEqual(f.props.modelValue, current)
  assert.deepEqual(f.updates, [])
  assert.equal(f.controller.data.state.session_id, 'session-b')
  assert.equal(f.controller.data.tab, 'create')
  assert.equal(f.calls.length, callsBefore)
  assert.equal(f.mutations.some(value => value.path.endsWith('/process')), false)
})
