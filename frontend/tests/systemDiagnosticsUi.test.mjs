import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRenderer, h, nextTick } from 'vue'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'
const uri = code => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
const compile = code => ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
const descendants = (node, tag) => [node, ...(node.children ?? []).flatMap(child => descendants(child, tag))].filter(value => value.tag === tag)
const text = node => [node.text ?? '', ...(node.children ?? []).map(text)].join('')
const flush = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)) }
const defaults = { enabled: true, detailed_logging: false, log_directory: 'log', retention_files: 5 }
async function fixture(t, initial = defaults) {
  const key = `diagnostics-${crypto.randomUUID()}`, calls = []
  let stored = { ...initial }, failLoad = false, failSave = false, pending = null
  globalThis[key] = async (path, options) => {
    const body = options.body ? JSON.parse(options.body) : undefined
    calls.push({ path, method: options.method, body })
    if (options.method === 'GET') return failLoad ? Response.json({}, { status: 503 }) : Response.json(stored)
    if (pending) await pending
    if (failSave) return Response.json({ detail: 'Internal failure details' }, { status: 503 })
    stored = { ...stored, ...body }
    return Response.json(stored)
  }
  const http = `${uri('export const apiFetch = (...args) => globalThis[new URL(import.meta.url).hash.slice(1)](...args)')}#${key}`
  const service = uri(compile(readFileSync(new URL('../src/services/systemDiagnosticsService.ts', import.meta.url), 'utf8')).replace("from '@/services/http'", `from '${http}'`))
  const { descriptor } = parse(readFileSync(new URL('../src/components/admin/SystemDiagnosticsSection.vue', import.meta.url), 'utf8'))
  const source = compile(compileScript(descriptor, { id: key, inlineTemplate: true }).content)
    .replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
    .replace("from '@/services/systemDiagnosticsService'", `from '${service}'`)
  const Section = (await import(uri(source))).default
  const element = tag => ({ tag, tagName: tag.toUpperCase(), props: {}, children: [], addEventListener() {}, removeEventListener() {} })
  const renderer = createRenderer({
    createElement: element, createText: value => ({ tag: '#text', text: value }), createComment: value => ({ tag: '#comment', text: value }),
    setText: (node, value) => { node.text = value }, setElementText: (node, value) => { node.text = value; node.children = [] },
    patchProp: (node, property, _previous, value) => { node.props[property] = value; node[property] = value },
    insert(node, parent, anchor) { if (node.parent) { const old = node.parent.children; old.splice(old.indexOf(node), 1) } node.parent = parent; const index = parent.children.indexOf(anchor); parent.children.splice(index < 0 ? parent.children.length : index, 0, node) },
    remove(node) { const siblings = node.parent.children; siblings.splice(siblings.indexOf(node), 1) }, parentNode: node => node.parent, nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1],
  })
  const root = element('root'), app = renderer.createApp({ render: () => h(Section) })
  app.mount(root); await flush()
  t.after(() => { app.unmount(); delete globalThis[key] })
  const input = label => { const node = descendants(root, 'label').find(value => text(value).includes(label)); assert.ok(node, `Missing ${label} control`); return descendants(node, 'input')[0] }
  const saveButton = () => descendants(root, 'button').find(node => text(node).includes('Save Diagnostics Settings') || text(node).includes('Saving…'))
  return { root, calls, input, saveButton, stored: () => stored,
    set(label, value) { input(label).props['onUpdate:modelValue'](value) },
    async save() { const form = descendants(root, 'form')[0]; await form.props.onSubmit({ preventDefault() {} }); await flush() },
    failLoad(value) { failLoad = value }, failSave(value) { failSave = value },
    holdSave(promise) { pending = promise },
  }
}
test('legacy diagnostics load both sibling controls without enabling failure traces or saving', async t => {
  const f = await fixture(t)
  assert.equal(f.input('State rejection traces').checked, false)
  assert.equal(f.input('Detailed logging').checked, false)
  assert.equal(f.saveButton().props.disabled, true)
  assert.match(text(f.root), /private state and LLM trace files/)
  assert.match(text(f.root), /rejected or remains unconfirmed/)
  assert.deepEqual(f.calls.map(value => value.method), ['GET'])
})
test('failure traces and detailed logging remain independent drafts until explicit save', async t => {
  const f = await fixture(t)
  f.set('State rejection traces', true); await flush()
  assert.equal(f.input('Detailed logging').checked, false); assert.equal(f.saveButton().props.disabled, false)
  assert.equal(f.calls.length, 1)
  await f.save()
  assert.deepEqual(f.calls.at(-1).body, { enabled: true, detailed_logging: false, state_failure_traces: true })
  assert.equal(f.saveButton().props.disabled, true)
  f.set('Detailed logging', true); f.set('State rejection traces', false); await flush()
  await f.save()
  assert.deepEqual(f.calls.at(-1).body, { enabled: true, detailed_logging: true, state_failure_traces: false })
  assert.match(text(f.root), /Include complete LLM prompts and responses/)
})
test('System Debug gates both sibling options and saving master-off clears both flags', async t => {
  const f = await fixture(t, { ...defaults, detailed_logging: true, state_failure_traces: true })
  f.set('System Debug', false); await flush()
  assert.equal(f.input('Detailed logging').props.disabled, true)
  assert.equal(f.input('State rejection traces').props.disabled, true)
  assert.equal(f.calls.length, 1)
  await f.save()
  assert.deepEqual(f.calls.at(-1).body, { enabled: false, detailed_logging: false, state_failure_traces: false })
  assert.equal(f.input('Detailed logging').checked, false); assert.equal(f.input('State rejection traces').checked, false)
})
test('a failed save keeps independent draft changes and permits explicit retry', async t => {
  const f = await fixture(t)
  f.set('State rejection traces', true); await flush(); f.failSave(true)
  await f.save()
  assert.match(text(f.root), /The setting could not be saved/)
  assert.doesNotMatch(text(f.root), /Internal failure details/)
  assert.equal(f.input('State rejection traces').checked, true); assert.equal(f.saveButton().props.disabled, false)
  f.failSave(false); await f.save()
  assert.equal(f.stored().state_failure_traces, true); assert.equal(f.saveButton().props.disabled, true)
})
test('saving disables the entire diagnostics form until the response finishes', async t => {
  const f = await fixture(t)
  let finish
  f.holdSave(new Promise(resolve => { finish = resolve }))
  f.set('State rejection traces', true)
  const saving = f.save(); await flush()
  assert.equal(descendants(f.root, 'fieldset')[0].props.disabled, true)
  assert.match(text(f.saveButton()), /Saving/)
  finish(); await saving
  assert.equal(descendants(f.root, 'fieldset')[0].props.disabled, false)
})
