import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { loadSfc, mountSfc, settle, stubComponent } from './mountSfc.mjs'

const quotes = { exports: {} }
new Function('module', 'exports', ts.transpileModule(readFileSync(new URL('../src/utils/wardrobeQuotes.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText)(quotes, quotes.exports)
const slots = { exports: {} }
new Function('module', 'exports', ts.transpileModule(readFileSync(new URL('../src/utils/equipmentSlots.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText)(slots, slots.exports)

for (const slot of ['vaginal', 'anal', 'uterine', 'penile']) test(`a rejected placement ${slot} can be corrected with an exact quote without applying state`, async t => {
  const previous = { Document: globalThis.Document, ShadowRoot: globalThis.ShadowRoot }
  globalThis.Document = class Document {}
  globalThis.ShadowRoot = class ShadowRoot {}
  t.after(() => {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete globalThis[key]
      else globalThis[key] = value
    }
  })
  const calls = [], text = 'Lina keeps the sealed medical sensor in the recorded body slot.'
  const view = mountSfc('components/game/DebugBodyPlacementCorrection.vue', {
    entry: { index: 3, attachment_slot: slot, evidence: 'A paraphrase.' }, source: text,
    token: 'preview', busy: false, selectedQuote: text, onCommand: command => calls.push(command),
  }, { '@/utils/wardrobeQuotes': quotes.exports, '@/utils/equipmentSlots': slots.exports })
  t.after(() => view.app.unmount())
  assert.deepEqual(view.all().filter(node => node.type === 'option').map(node => node.props.value), ['vaginal', 'anal', 'uterine', 'penile'])
  assert.equal(view.button('Validate correction').props.disabled, true)
  view.button('Use selected source passage').props.onClick()
  await settle()
  assert.equal(view.button('Validate correction').props.disabled, false)
  view.all().find(node => node.type === 'form').props.onSubmit({ preventDefault() {} })
  assert.equal(calls.length, 1)
  const prefix = '/debug wardrobe_correct preview 3 '
  assert.ok(calls[0].startsWith(prefix))
  assert.deepEqual(JSON.parse(calls[0].slice(prefix.length)), { status: 'worn', evidence: text, attachment_slot: slot })
})

test('player-sourced item previews are labelled and are unselected by default', t => {
  const view = mountSfc('components/game/DebugWardrobeRecovery.vue', {
    npcId: 'LINA', busy: false,
    preview: { token: 'p', notes: '', messages_scanned: 2, limited: false, errors: [],
      source_roles: { old: 'user' }, accepted: [{ proposal_index: 0, item: { name: 'Sealed tube', description: 'Small glass tube.' },
        disposition: 'worn', attachment_slot: 'vaginal', source_role: 'user', source_message_id: 'old', evidence: 'The original placement.' }] },
  }, { './DebugWardrobeMentions.vue': { default: stubComponent }, './DebugWardrobeRejections.vue': { default: stubComponent }, './DebugRecoveryManual.vue': { default: stubComponent } })
  t.after(() => view.app.unmount())
  assert.match(view.all().map(view.text).join(' '), /Player message/)
  assert.equal(view.button('Restore selected items').props.disabled, true)
})

test('debug offers removal without editing metadata and keeps body items out of the garment editor', t => {
  const calls = []
  const row = loadSfc('components/game/DebugWardrobeItem.vue', { './DebugItemRepair.vue': { default: stubComponent }, 'lucide-vue-next': { Pencil: stubComponent } })
  const view = mountSfc('components/game/DebugNpcClothing.vue', {
    busy: false, npc: { id: 'LINA', wardrobe: { profile_known: true, items: [
      { id: 'COAT', name: 'Coat', worn: true, clothing: { layer: 3, coverage: ['torso'] } },
      { id: 'TUBE', name: 'Tube', worn: true, attachment_slot: 'vaginal', clothing: null },
    ] } }, onCommand: command => calls.push(command),
  }, { './DebugWardrobePreferences.vue': { default: stubComponent }, './DebugWardrobeRecovery.vue': { default: stubComponent },
    './DebugWardrobeItem.vue': { default: row } })
  t.after(() => view.app.unmount())
  view.button('Take off').props.onClick()
  view.button('Remove item').props.onClick()
  assert.deepEqual(calls.map(command => JSON.parse(command.slice('/debug npc_unwear '.length))), [
    { npc_id: 'LINA', item_id: 'COAT' }, { npc_id: 'LINA', item_id: 'TUBE' },
  ])
  assert.equal(view.all().filter(node => node.type === 'button' && view.text(node).trim() === 'Edit').length, 1)
})

test('carried pajamas stay outside worn layers and room clothes offer canonical take/wear actions', t => {
  const row = loadSfc('components/game/DebugWardrobeItem.vue', { './DebugItemRepair.vue': { default: stubComponent }, 'lucide-vue-next': { Pencil: stubComponent } })
  const calls = []
  const view = mountSfc('components/game/DebugNpcClothing.vue', {
    busy: false, npc: { id: 'MIKI', wardrobe: { profile_known: true,
      items: [{ id: 'PAJAMA', name: 'Пижама', worn: false, clothing: { layer: 3, coverage: ['torso'] } }],
      scene_items: [{ id: 'COAT', name: 'Халат', worn: false, location: 'scene', spatial_position: 'на кровати', clothing: { layer: 3, coverage: ['torso'] } }],
    } }, onCommand: command => calls.push(command),
  }, { './DebugWardrobePreferences.vue': { default: stubComponent }, './DebugWardrobeRecovery.vue': { default: stubComponent }, './DebugWardrobeItem.vue': { default: row } })
  t.after(() => view.app.unmount())
  assert.equal(view.all().filter(node => node.props['data-clothing-layer']).length, 0)
  const inventory = view.all().find(node => node.props['data-wardrobe-section'] === 'inventory')
  const scene = view.all().find(node => node.props['data-wardrobe-section'] === 'scene')
  assert.match(view.text(inventory), /Пижама/)
  assert.match(view.text(scene), /Халат.*на кровати/)
  view.button('Take into inventory').props.onClick()
  assert.deepEqual(JSON.parse(calls[0].slice('/debug npc_wardrobe '.length)), { npc_id: 'MIKI', item_id: 'COAT', operation: 'carry' })
})
