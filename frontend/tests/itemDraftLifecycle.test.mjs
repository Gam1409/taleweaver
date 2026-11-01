import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { parse, compileScript } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive } from 'vue'
import ts from 'typescript'

const require = createRequire(import.meta.url)
function mountGenerator() {
  const requests = []
  const source = readFileSync(new URL('../src/components/editor/ItemDraftGenerator.vue', import.meta.url), 'utf8')
    .replace('</script>', 'defineExpose({ generate, brief, busy, error, generated })\n</script>')
  const { descriptor } = parse(source)
  const compiled = compileScript(descriptor, { id: 'item-draft-lifecycle' }).content
  const code = ts.transpileModule(compiled, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  const module = { exports: {} }
  const dependency = name => name === '@/services/itemGeneration'
    ? { generateItemDraft: (...args) => new Promise((resolve, reject) => requests.push({ args, resolve, reject })) }
    : require(name)
  new Function('require', 'module', 'exports', code)(dependency, module, module.exports)
  const component = module.exports.default
  component.render = () => null
  const renderer = createRenderer({
    createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
    insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {},
    parentNode: () => null, nextSibling: () => null,
  })
  const props = reactive({ adventureId: 'a', itemType: 'DEFAULT', fixedSlots: [], contextVersion: 0 })
  const drafts = [], busyEvents = []
  let view
  const app = renderer.createApp({ render: () => h(component, {
    ...props, ref: instance => { view = instance },
    onDraft: draft => drafts.push(draft), onBusy: busy => busyEvents.push(busy),
  }) })
  app.mount({})
  view.brief = 'A key'
  return { view, props, requests, drafts, busyEvents, app }
}

test('equivalent slot arrays do not cancel a draft on parent rerender', async () => {
  const v = mountGenerator()
  const pending = v.view.generate()
  v.props.fixedSlots = []
  await nextTick()
  assert.equal(v.view.busy, true)
  v.requests[0].resolve({ name: 'Key' })
  await pending
  assert.deepEqual(v.drafts, [{ name: 'Key' }])
  v.app.unmount()
})

test('old completion cannot update a new context or clear its busy state', async () => {
  const v = mountGenerator()
  const old = v.view.generate()
  v.props.contextVersion++
  await nextTick()
  const current = v.view.generate()
  v.requests[0].resolve({ name: 'Old key' })
  await old
  assert.equal(v.view.busy, true)
  assert.deepEqual(v.drafts, [])
  v.requests[1].resolve({ name: 'New key' })
  await current
  assert.deepEqual(v.drafts, [{ name: 'New key' }])
  assert.equal(v.view.busy, false)
  v.app.unmount()
})

test('unmount releases parent busy state and ignores late errors', async () => {
  const v = mountGenerator()
  const pending = v.view.generate()
  v.app.unmount()
  assert.equal(v.busyEvents.at(-1), false)
  v.requests[0].reject(new Error('Late failure'))
  await pending
  assert.deepEqual(v.drafts, [])
})
