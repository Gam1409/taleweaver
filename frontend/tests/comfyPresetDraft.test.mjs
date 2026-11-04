import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const source = readFileSync(new URL('../src/services/comfyPresetDraft.ts', import.meta.url), 'utf8')
const library = ts.transpileModule(readFileSync(new URL('../src/services/comfyLibrary.ts', import.meta.url), 'utf8'), {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext}}).outputText
const libraryUri = `data:text/javascript;base64,${Buffer.from(library).toString('base64')}`
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
}).outputText.replaceAll("'./comfyLibrary'", JSON.stringify(libraryUri))
const { addStarterPreset, presetWorkspace, newPreset, applyPresetWorkspace, presetProblem, removePreset } =
  await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
const preset = name => ({
  name,
  generate: {
    name: 'Workflow',
    graph: {},
    bindings: { prompt: { node_id: '1', input_name: 'text' } },
    output_node: '2'
  },
  reference: null,
  prompt_rules: null,
  auto_prompt_template: false
})
const options = () => ({
  comfyui_url: 'http://localhost:8188',
  comfyui_timeout: 600,
  comfyui_profiles: {},
  comfyui_presets: { a: preset('A'), b: preset('B') },
  comfyui_assignments: { simple: 'a', advanced: 'b' }
})

test('switching presets retains edits without mutating the form', () => {
  const original = options()
  const workspace = presetWorkspace(original, 'simple')
  workspace.presets.a.name = 'A edited'
  workspace.selectedId = 'b'
  workspace.presets.b.name = 'B edited'
  workspace.selectedId = 'a'
  assert.equal(workspace.presets.a.name, 'A edited')
  assert.equal(original.comfyui_presets.a.name, 'A')
  const applied = applyPresetWorkspace(original, workspace, 'simple')
  assert.equal(applied.comfyui_presets.b.name, 'B edited')
  assert.equal(applied.comfyui_assignments.advanced, 'b')
})
test('apply merges edits into fresh settings and preserves unrelated changes', () => {
  const original = options()
  const workspace = presetWorkspace(original, 'simple')
  workspace.presets.a.name = 'Local edit'
  const latest = {
    ...original,
    comfyui_url: 'http://new-host:8188',
    comfyui_presets: {
      ...original.comfyui_presets,
      b: preset('Remote edit'),
      c: preset('New elsewhere')
    },
    comfyui_assignments: { ...original.comfyui_assignments, advanced: 'c' }
  }
  const applied = applyPresetWorkspace(latest, workspace, 'simple')
  assert.equal(applied.comfyui_url, latest.comfyui_url)
  assert.equal(applied.comfyui_presets.b.name, 'Remote edit')
  assert.equal(applied.comfyui_presets.c.name, 'New elsewhere')
  assert.equal(applied.comfyui_assignments.advanced, 'c')
  assert.equal(applied.comfyui_presets.a.name, 'Local edit')
})
test('duplicate edits are isolated and discard is just dropping the workspace', () => {
  const original = options()
  const workspace = presetWorkspace(original, 'simple')
  const id = newPreset(workspace, true)
  workspace.presets[id].generate.output_node = 'changed'
  assert.equal(workspace.presets.a.generate.output_node, '2')
  assert.equal(Object.keys(original.comfyui_presets).length, 2)
  assert.equal(workspace.presets[id].name, 'A copy')
})
test('saved presets and unsaved drafts can be removed while keeping one selected', () => {
  const workspace = presetWorkspace(options(), 'simple')
  removePreset(workspace)
  assert.equal(workspace.presets.a, undefined)
  assert.equal(workspace.selectedId, 'b')
  const id = newPreset(workspace)
  assert.match(presetProblem(workspace.presets[id]), /base workflow/)
  removePreset(workspace)
  assert.equal(workspace.presets[id], undefined)
  assert.ok(workspace.presets[workspace.selectedId])
})
test('connection edits apply with the preset and untouched originals stay independent', () => {
  const original = options()
  const workspace = presetWorkspace(original, 'simple')
  workspace.url = 'http://render:8188'
  workspace.timeout = 900
  workspace.selectedId = 'b'
  const applied = applyPresetWorkspace(original, workspace, 'simple')
  assert.equal(applied.comfyui_url, workspace.url)
  assert.equal(applied.comfyui_timeout, 900)
  assert.equal(applied.comfyui_assignments.simple, 'b')
  assert.equal(original.comfyui_assignments.simple, 'a')
})
test('missing automatic templates and incomplete references are actionable', () => {
  const item = preset('A')
  item.auto_prompt_template = true
  assert.match(presetProblem(item), /template/)
  item.auto_prompt_template = false
  item.reference = { ...item.generate }
  assert.match(presetProblem(item), /reference workflow/)
})
test('an empty library starts with one editable draft and the 32-preset limit is enforced', () => {
  const workspace = presetWorkspace({ ...options(), comfyui_presets: {} }, 'simple')
  assert.equal(Object.keys(workspace.presets).length, 1)
  removePreset(workspace)
  assert.equal(Object.keys(workspace.presets).length, 1)
  while (Object.keys(workspace.presets).length < 32) newPreset(workspace)
  assert.throws(() => newPreset(workspace), /at most 32/)
})

test('task assignment preserves other tasks and shared quality profiles', () => {
  const original = options()
  original.comfyui_assignments.illustration = 'a'
  const workspace = presetWorkspace(original, 'background')
  workspace.selectedId = 'b'
  const applied = applyPresetWorkspace(original, workspace, 'background')
  assert.deepEqual(applied.comfyui_assignments, {
    simple: 'a', advanced: 'b', illustration: 'a', background: 'b'
  })
  assert.equal(original.comfyui_assignments.background, undefined)
})

test('unassigned task editor opens its inherited preset', () => {
  const workspace = presetWorkspace(options(), 'background', 'advanced')
  assert.equal(workspace.selectedId, 'b')
})

const { filterPresets, workflowDependencies, rememberWorkflows } = await import(libraryUri)
test('library filters combine name/style/model search, task and reference capability', () => {
  const presets = { a: {...preset('Gothic scenes'), purpose_tags: ['background'], style_tags: ['monochrome']}, b: {...preset('Portrait'), purpose_tags: ['npc'], reference: {bindings: {image: {}}}} }
  assert.deepEqual(filterPresets(presets, {query:'MONO', task:'background', reference:'no'}).map(([id])=>id), ['a'])
  assert.deepEqual(filterPresets(presets, {query:'', task:'npc', reference:'yes'}).map(([id])=>id), ['b'])
  assert.equal(filterPresets(presets, {query:'', task:'npc', reference:'no'}).length, 0)
})
test('editing a workflow creates an independent version without changing other presets', () => {
  const first = preset('A')
  first.generate.graph = { model: {class_type:'CheckpointLoaderSimple', inputs:{ckpt_name:'model.safetensors'}} }
  const v1 = rememberWorkflows({}, {a:first})
  const original = JSON.stringify(v1)
  const edited = structuredClone(first)
  edited.generate.graph.model.inputs.ckpt_name = 'new.safetensors'
  const v2 = rememberWorkflows(v1, {a:edited})
  assert.equal(Object.keys(v2).length, 2)
  assert.equal(JSON.stringify(v1), original)
  assert.equal(first.generate.graph.model.inputs.ckpt_name, 'model.safetensors')
  assert.deepEqual(Object.values(v2).map(v=>v.revision), [1,2])
  assert.equal(Object.keys(rememberWorkflows(v2, {a:edited})).length, 2)
  assert.deepEqual(workflowDependencies(edited.generate), ['CheckpointLoaderSimple · ckpt_name: new.safetensors'])
})
test('removing a library version preserves pinned workflow and concurrent library additions', () => {
  const initial = options()
  initial.comfyui_workflows = rememberWorkflows({}, initial.comfyui_presets)
  const workspace = presetWorkspace(initial,'simple')
  const removed = Object.keys(workspace.workflows)[0]
  delete workspace.workflows[removed]
  const current = structuredClone(initial)
  current.comfyui_workflows.remote = {revision:1,workflow: {...preset('Remote').generate,name:'Remote'}}
  const applied = applyPresetWorkspace(current,workspace,'simple')
  assert.equal(applied.comfyui_workflows[removed], undefined)
  assert.ok(applied.comfyui_workflows.remote)
  assert.deepEqual(applied.comfyui_presets.a.generate, initial.comfyui_presets.a.generate)
})


test('creating a starter replaces only an untouched empty draft and isolates the source', () => {
  const original = {...options(), comfyui_presets: {}, comfyui_assignments: {}}
  const workspace = presetWorkspace(original, 'simple')
  const id = workspace.selectedId
  const template = {...preset('SDXL portrait'), purpose_tags:['npc']}
  addStarterPreset(workspace, template)
  assert.equal(workspace.selectedId, id)
  assert.equal(Object.keys(workspace.presets).length, 1)
  workspace.presets[id].name = 'My portrait'
  assert.equal(template.name, 'SDXL portrait')
  addStarterPreset(workspace, template)
  assert.notEqual(workspace.selectedId, id)
  assert.equal(workspace.presets[id].name, 'My portrait')
  assert.deepEqual(original.comfyui_presets, {})
})

test('HTTP LAN contexts can remember workflows without randomUUID or crypto', () => {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'crypto')
  try {
    for (const crypto of [{}, undefined]) {
      Object.defineProperty(globalThis, 'crypto', { configurable: true, value: crypto })
      const workspace = presetWorkspace(options(), 'simple')
      assert.ok(Object.keys(workspace.workflows).length)
      assert.ok(Object.values(workspace.workflows)[0].workflow)
    }
  } finally {
    if (original) Object.defineProperty(globalThis, 'crypto', original)
    else delete globalThis.crypto
  }
})

test('deletion applies only on save, clears dependent selections, and preserves concurrent additions', () => {
  const original = options()
  original.comfyui_assignments.npc = 'a'
  original.comfyui_test_preset = 'a'
  const workspace = presetWorkspace(original, 'simple')
  removePreset(workspace)
  assert.ok(original.comfyui_presets.a)
  const current = structuredClone(original)
  current.comfyui_presets.c = preset('Elsewhere')
  current.comfyui_assignments.background = 'c'
  const applied = applyPresetWorkspace(current, workspace, 'simple')
  assert.equal(applied.comfyui_presets.a, undefined)
  assert.ok(applied.comfyui_presets.b)
  assert.ok(applied.comfyui_presets.c)
  assert.deepEqual(applied.comfyui_assignments, { simple:'b', advanced:'b', background:'c' })
  assert.equal(applied.comfyui_test_preset, null)
  assert.ok(Object.keys(applied.comfyui_workflows).length)
})

test('deletion frees a full library slot and protects concurrent preset edits', () => {
  const original = options()
  const workspace = presetWorkspace(original, 'simple')
  while (Object.keys(workspace.presets).length < 32) newPreset(workspace)
  workspace.selectedId = 'a'
  removePreset(workspace)
  assert.doesNotThrow(() => newPreset(workspace))
  assert.equal(Object.keys(workspace.presets).length, 32)
  const changed = structuredClone(original)
  changed.comfyui_presets.a.name = 'Changed elsewhere'
  assert.throws(() => applyPresetWorkspace(changed, workspace, 'simple'), /changed elsewhere/)
})
