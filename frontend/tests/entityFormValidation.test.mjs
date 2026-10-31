import { test } from 'node:test'
import { Buffer } from 'node:buffer'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'
const source = readFileSync(new URL('../src/components/editor/entityFormValidation.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
const { entityFormErrors } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
const options = { hasEditableId: true, maxIdLength: 30, entityIdError: '', switchStates: [], switchTransitions: [] }
const npc = { name: 'Мики', description: 'Медсестра', entity_id: 'NURSE_MIKI' }

test('movement and permitted scenes do not prevent saving a valid NPC', () => {
  assert.deepEqual(entityFormErrors({ ...npc, moveable: true, allowed_scenes_input: ['HOSPITAL_CORRIDOR'] }, options), [])
})
test('loaded over-limit biography and personality explain why movement edits cannot save', () => {
  assert.deepEqual(entityFormErrors({ ...npc, description: 'я'.repeat(1001), character: 'x'.repeat(201) }, options), [
    'Description / Biography: 1001 characters; maximum 1000.',
    'Character / Traits: 201 characters; maximum 200.',
  ])
  assert.deepEqual(entityFormErrors({ ...npc, description: 'я'.repeat(1000), character: 'x'.repeat(200) }, options), [])
})
test('missing required fields and duplicate IDs have visible reasons', () => {
  assert.deepEqual(entityFormErrors({ ...npc, name: ' ', description: '' }, { ...options, entityIdError: 'ID already exists.' }), [
    'Name is required.', 'Description / Biography is required.', 'ID: ID already exists.',
  ])
})
test('constructable and switch constraints remain enforced', () => {
  assert.equal(entityFormErrors({ ...npc, item_type: 'CONSTRUCTABLE' }, options).length, 1)
  assert.equal(entityFormErrors({ ...npc, item_type: 'SWITCH' }, options).length, 2)
  assert.deepEqual(entityFormErrors({ ...npc, item_type: 'SWITCH', switch_initial_state: 'ON' }, {
    ...options, switchStates: ['OFF', 'ON'], switchTransitions: [{ from: 'OFF', to: 'ON' }],
  }), [])
})
