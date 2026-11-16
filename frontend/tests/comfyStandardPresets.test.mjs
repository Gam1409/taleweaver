import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import ts from 'typescript'

const uri = code => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
const compile = name => ts.transpileModule(readFileSync(new URL(`../src/services/${name}.ts`, import.meta.url), 'utf8'),
  {compilerOptions: {target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}}).outputText
const library = uri(compile('comfyLibrary'))
const draft = uri(compile('comfyPresetDraft').replaceAll("'./comfyLibrary'", JSON.stringify(library)))
const {presetWorkspace} = await import(draft)
const {addStandardPresets} = await import(uri(compile('comfyStandardPresets')
  .replaceAll("'./comfyLibrary'",JSON.stringify(library)).replaceAll("'./comfyPresetDraft'",JSON.stringify(draft))))
const preset = name => ({name,generate:{name,graph:{out:{class_type:'SaveImage',inputs:{}}},bindings:{},output_node:'out'},reference:null,prompt_rules:null,auto_prompt_template:false})
const options = {comfyui_url:'http://localhost:8188',comfyui_timeout:600,comfyui_profiles:{},comfyui_presets:{custom:preset('Custom')},comfyui_assignments:{npc:'custom'}}
const bundle = {comfyui_presets:{'standard-anima-npc':preset('NPC · Anima'),'standard-illustrious-npc':preset('NPC · Illustrious')}}

test('adding standards pins graphs, preserves user presets and is idempotent', () => {
  const workspace = presetWorkspace(options,'npc')
  const baseline = JSON.stringify(options)
  assert.equal(addStandardPresets(workspace,bundle,'npc'),2)
  assert.equal(workspace.presets.custom.name,'Custom')
  assert.equal(workspace.selectedId,'standard-anima-npc')
  assert.ok(Object.values(workspace.workflows).some(row => row.workflow.name === 'NPC · Anima'))
  assert.equal(addStandardPresets(workspace,bundle,'npc'),0)
  workspace.presets['standard-anima-npc'].name = 'Personal changes'
  assert.equal(addStandardPresets(workspace,bundle,'npc'),0)
  assert.equal(workspace.presets['standard-anima-npc'].name,'Personal changes')
  assert.equal(bundle.comfyui_presets['standard-anima-npc'].name,'NPC · Anima')
  assert.equal(JSON.stringify(options),baseline)
})

test('preset and workflow capacity errors leave the entire draft unchanged', () => {
  const workspace = presetWorkspace(options,'npc')
  workspace.presets = Object.fromEntries(Array.from({length:32},(_,i)=>[`p${i}`,preset(`Custom ${i}`)]))
  let before = JSON.stringify(workspace)
  assert.throws(()=>addStandardPresets(workspace,bundle),/32/)
  assert.equal(JSON.stringify(workspace),before)
  workspace.presets = {custom:preset('Custom')}
  workspace.workflows = Object.fromEntries(Array.from({length:128},(_,i)=>[`w${i}`,{revision:1,workflow:preset(`Workflow ${i}`).generate}]))
  before = JSON.stringify(workspace)
  assert.throws(()=>addStandardPresets(workspace,bundle),/128/)
  assert.equal(JSON.stringify(workspace),before)
})
