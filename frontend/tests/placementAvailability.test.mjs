import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { mountSfc, settle, stubComponent } from './mountSfc.mjs'

const utility = { exports: {} }
new Function('module', 'exports', ts.transpileModule(readFileSync(new URL('../src/utils/equipmentSlots.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText)(utility, utility.exports)
const snapshot = { exports: {} }
new Function('module', 'exports', ts.transpileModule(readFileSync(new URL('../src/utils/conditionSnapshot.ts', import.meta.url), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText)(snapshot, snapshot.exports)
function current(silhouette, placementStatus) {
  return { availability: 'present', game_minute: 10, layout: { form: 'humanoid', silhouette }, clothing: { status: 'available', detail_limited: false, items: [], placement_status: placementStatus, placement_slots: [] }, conditions: { status: 'available', items: [] } }
}
function fixture(t, state) {
  const view = mountSfc('components/game/NpcCurrentState.vue', { state, compact: true }, {
    '@/utils/equipmentSlots': utility.exports, '@/utils/conditionSnapshot': snapshot.exports, './EquipmentSilhouette.vue': { default: stubComponent }, './EquipmentList.vue': { default: stubComponent },
  })
  t.after(() => view.app.unmount())
  return view
}
async function showEmpty(view) {
  const checkbox = view.all().find(node => node.type === 'input' && node.props.type === 'checkbox')
  assert.ok(checkbox)
  checkbox.props['onUpdate:modelValue'](true)
  await settle()
}
for (const [variant, labels] of [['female', ['Vaginal area', 'Anal area', 'Uterus']], ['male', ['Anal area', 'Penile area']], ['neutral', ['Vaginal area', 'Anal area', 'Uterus', 'Penile area']]]) {
  test(`showing empty positions exposes unassessed ${variant} layout markers without asserting anatomy`, async t => {
    const state = current(variant, 'unassessed'), before = structuredClone(state), view = fixture(t, state)
    await showEmpty(view)
    const area = view.all().find(node => node.props['aria-label'] === 'Additional placement areas')
    assert.ok(area)
    assert.equal(area.children.filter(node => node.type === 'li').length, labels.length)
    for (const label of labels) assert.ok(view.text(area).includes(label))
    assert.match(view.text(area), /Not assessed/)
    assert.doesNotMatch(view.text(area), /Item recorded|No recorded item/)
    assert.deepEqual(state, before)
  })
}
for (const status of [undefined, 'unavailable', 'available']) {
  test(`unassessed placeholders never override missing or explicit ${status} availability`, async t => {
    const view = fixture(t, current('female', status))
    await showEmpty(view)
    assert.equal(view.all().some(node => node.props['aria-label'] === 'Additional placement areas'), false)
  })
}
