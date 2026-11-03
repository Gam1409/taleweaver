import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const source = readFileSync(new URL('../src/services/comfyPresetDraft.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
}).outputText
const { presetWorkspace, newPreset, applyPresetWorkspace, presetProblem, removeUnsavedPreset } =
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
test('unsaved drafts can be removed without deleting saved presets', () => {
  const workspace = presetWorkspace(options(), 'simple')
  removeUnsavedPreset(workspace)
  assert.ok(workspace.presets.a)
  const id = newPreset(workspace)
  assert.match(presetProblem(workspace.presets[id]), /base workflow/)
  removeUnsavedPreset(workspace)
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
  removeUnsavedPreset(workspace)
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
