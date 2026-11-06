import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { effectScope, reactive, nextTick } from 'vue'
import ts from 'typescript'

const deferred = () => {
  let resolve, reject
  const promise = new Promise((a, b) => {
    resolve = a
    reject = b
  })
  return { promise, resolve, reject }
}
const tick = async () => {
  await nextTick()
  await new Promise(resolve => setImmediate(resolve))
}
const workflow = kind => ({
  name: kind,
  graph: { model: { class_type: kind, inputs: { model_name: 'x' } } },
  bindings: {},
  output_node: ''
})
let id = 0
async function mount(t, source, props, request, editor = false) {
  const key = `__comfyAsync${id++}`
  const ctx = { props: reactive(props), request, busy: [], emitted: [], cleanup: [] }
  globalThis[key] = ctx
  source = source.replace(/import[\s\S]*?from ['"][^'"]+['"];?/g, '')
  if (editor === 'slot') {
    source = source
      .replace(/const props = defineProps<[\s\S]*?>\(\)/, `const props = globalThis['${key}'].props`)
      .replace(/const emit = defineEmits<[\s\S]*?>\(\)/,
        `const emit = (...args) => globalThis['${key}'].emitted.push(args)`)
      .replace(/const \{ (importWorkflowGraphWithServer|suggestBindings) \} = await import\([^\n]+\)/g, '')
    source = `export function setup() { const defineAsyncComponent = () => null; ${source}; return {importFile, report, selected}; }`
  } else if (editor) {
    source = source
      .replace(/const props = defineProps<[^\n]+\(\)/, `const props = globalThis['${key}'].props`)
      .replace(
        /const emit = defineEmits<[^\n]+\(\)/,
        `const emit = (...args) => globalThis['${key}'].emitted.push(args)`
      )
    source = `export function setup() { ${source}; return {loadWorkflow, importing, checkNodes, nodeReport}; }`
  }
  source = `import {computed, ref, watch, nextTick} from '${import.meta.resolve('vue')}';
const onBeforeUnmount = cb => globalThis['${key}'].cleanup.push(cb);
const comfyRequest = (...args) => globalThis['${key}'].request(...args);
const importWorkflowGraphWithServer = (...args) => globalThis['${key}'].request(...args);
const suggestBindings = () => ({bindings:{},output_node:'out',notes:[]});
const existingPositions = () => ({});
const clonePresetData = value => JSON.parse(JSON.stringify(value));
${source}`
  const compiled = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
  }).outputText
  const mod = await import(
    `data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`
  )
  const scope = effectScope()
  const result = scope.run(() =>
    editor ? mod.setup() : mod.useComfyModelOptions(ctx.props, value => ctx.busy.push(value))
  )
  const unmount = () => {
    ctx.cleanup.splice(0).forEach(cb => cb())
    scope.stop()
  }
  t.after(() => {
    unmount()
    delete globalThis[key]
  })
  return { ctx, result, unmount }
}

const optionsSource = readFileSync(
  new URL('../src/composables/useComfyModelOptions.ts', import.meta.url),
  'utf8'
)
const editorSource = readFileSync(
  new URL('../src/components/admin/ComfyWorkflowEditor.vue', import.meta.url),
  'utf8'
).match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]

test('model choices refresh on class and URL changes; stale errors cannot erase new choices', async t => {
  const requests = []
  const f = await mount(
    t,
    optionsSource,
    { url: 'https://one', modelValue: workflow('LoaderA') },
    () => {
      const d = deferred()
      requests.push(d)
      return d.promise
    }
  )
  f.ctx.props.modelValue = workflow('LoaderB')
  await tick()
  assert.equal(requests.length, 2)
  requests[1].resolve([{ node_id: 'model', input_name: 'model_name', choices: ['new'] }])
  await tick()
  requests[0].reject(new Error('old failure'))
  await tick()
  assert.deepEqual(f.result.choicesFor('model', 'model_name'), ['new'])
  f.ctx.props.url = 'https://two'
  await tick()
  assert.equal(requests.length, 3)
  assert.equal(f.result.choicesFor('model', 'model_name'), undefined)
  f.unmount()
  requests[2].resolve([{ node_id: 'model', input_name: 'model_name', choices: ['late'] }])
  await tick()
  assert.equal(f.result.choicesFor('model', 'model_name'), undefined)
})

for (const action of ['replace', 'unmount', 'new import']) {
  test(`pending import cannot overwrite a workflow after ${action}`, async t => {
    const requests = []
    const f = await mount(
      t,
      editorSource,
      { url: 'https://one', modelValue: workflow('Before') },
      () => {
        const d = deferred()
        requests.push(d)
        return d.promise
      },
      true
    )
    const event = () => ({
      target: {
        files: [{ name: 'graph.json', size: 2, text: async () => '{}' }],
        value: 'graph.json'
      }
    })
    const first = f.result.loadWorkflow(event())
    await tick()
    let second
    if (action === 'replace') f.ctx.props.modelValue = workflow('After')
    if (action === 'unmount') f.unmount()
    if (action === 'new import') {
      second = f.result.loadWorkflow(event())
      await tick()
    }
    requests[0].resolve({ graph: workflow('Old').graph, notes: [] })
    await first
    assert.equal(f.ctx.emitted.filter(e => e[0] === 'update:modelValue').length, 0)
    if (second) {
      requests[1].resolve({ graph: workflow('New').graph, notes: [] })
      await second
      assert.equal(f.ctx.emitted.filter(e => e[0] === 'update:modelValue').length, 1)
    }
  })
}


test('node check works without bindings and clears results when workflow changes', async t => {
  const calls = []
  const f = await mount(t, editorSource, {url: 'https://server', modelValue: workflow('MissingLoader')}, async (...args) => {
    calls.push(args)
    return {node_types: 1, missing_node_types: ['MissingLoader']}
  }, true)
  await f.result.checkNodes()
  assert.deepEqual(calls[0], ['check-nodes', {url:'https://server', classes:['MissingLoader']}])
  assert.deepEqual([...f.result.nodeReport.value], ['Missing node type: MissingLoader'])
  f.ctx.props.modelValue = workflow('InstalledLoader')
  assert.equal(f.result.nodeReport.value.length, 0)
})

test('visual editor trims imported workflow names to the API limit', async t => {
  const f = await mount(t, editorSource,
    {url: 'https://one', modelValue: workflow('Before')},
    async () => ({graph: {out: {class_type:'SaveImage', inputs:{}}}, notes: []}), true)
  const name = 'a'.repeat(140) + '.json'
  await f.result.loadWorkflow({target: {files: [{name, size: 2, text: async () => '{}'}], value: name}})
  const update = f.ctx.emitted.find(([event]) => event === 'update:modelValue')
  assert.ok(update)
  assert.equal(update[1].name, name.slice(0, 120))
})

const slotSource = readFileSync(
  new URL('../src/components/admin/ComfyWorkflowSlot.vue', import.meta.url), 'utf8'
).match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]

test('saved workflow selection survives parent updates and remounting the tab', async t => {
  const library = {a: {workflow: workflow('A'), revision: 1}, b: {workflow: workflow('B'), revision: 1}}
  const props = {url: 'https://one', modelValue: structuredClone(library.a.workflow), library}
  const first = await mount(t, slotSource, props, async () => ({}), 'slot')
  assert.equal(first.result.selected.value, 'a')
  first.result.selected.value = 'b'
  const update = first.ctx.emitted.find(([event]) => event === 'update:modelValue')
  assert.ok(update)
  first.ctx.props.modelValue = structuredClone(update[1])
  await tick()
  assert.equal(first.result.selected.value, 'b')
  first.unmount()
  const remounted = await mount(t, slotSource, {...props, modelValue: update[1]}, async () => ({}), 'slot')
  assert.equal(remounted.result.selected.value, 'b')
  assert.deepEqual(remounted.ctx.props.modelValue, library.b.workflow)
  remounted.ctx.props.modelValue = workflow('Unsaved custom graph')
  await tick()
  assert.equal(remounted.result.selected.value, '')
})

test('slot import warnings survive parent v-model updates and clear when source changes', async t => {
  const notes = ['Unknown node: positional widgets were skipped instead of guessing.']
  const f = await mount(t, slotSource,
    {url: 'https://one', modelValue: workflow('Before'), library: {}},
    async () => ({graph: {out: {class_type:'CustomNode', inputs:{}}}, notes}), 'slot')
  await f.result.importFile({target: {files: [{name:'custom.json', size:2, text:async ()=>'{}'}], value:'custom.json'}})
  const update = f.ctx.emitted.find(([event]) => event === 'update:modelValue')
  assert.ok(update)
  f.ctx.props.modelValue = structuredClone(update[1])
  await tick()
  assert.deepEqual([...f.result.report.value], notes)
  f.ctx.props.url = 'https://two'
  await tick()
  assert.deepEqual([...f.result.report.value], [])
})

test('stale slot imports cannot restore warnings after switching workflows', async t => {
  const pending = deferred()
  const f = await mount(t, slotSource,
    {url: 'https://one', modelValue: workflow('Before'), library: {}},
    () => pending.promise, 'slot')
  const loading = f.result.importFile({target: {files: [{name:'custom.json', size:2, text:async ()=>'{}'}], value:'custom.json'}})
  await tick()
  f.ctx.props.modelValue = workflow('After')
  await tick()
  pending.resolve({graph:{}, notes:['Old warning']})
  await loading
  assert.deepEqual([...f.result.report.value], [])
  assert.equal(f.ctx.emitted.length, 0)
})
