import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ref } from 'vue'
import ts from 'typescript'
import { mountSfc, stubComponent, settle } from './mountSfc.mjs'

const fieldsSource = readFileSync(new URL('../src/services/itemDraftFields.ts', import.meta.url), 'utf8')
const { itemDraftFields } = await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(fieldsSource, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
}).outputText).toString('base64')}`)
const props = () => ({
  editorObjects: [], editorSwitches: [], editorContainers: [], editorTextLogs: [],
  isBatchGenerating: {}, isQuickGenerating: {}, activeMenuId: null, ruleEnforcementMode: 'strict',
  visualsCacheVersion: 1, editorScenes: [{ id: 'LAB', name: 'Laboratory' }], activeMapSceneId: null,
})
const dependencies = {
  './EditorActionMenu.vue': stubComponent,
  'lucide-vue-next': { Brain: stubComponent, Plus: stubComponent },
  '@/utils/editor_utils': { hasAnyScript: () => false },
}

test('Items offers Add even when no items or active map scene exist', () => {
  const events = []
  const view = mountSfc('components/editor/ItemsTab.vue', { ...props(), onAddItem: id => events.push(id) }, dependencies)
  assert.ok(view.button('Add'))
  view.button('Add').props.onClick()
  assert.deepEqual(events, [null])
  view.app.unmount()
})

test('Add respects the current scene filter', async () => {
  const events = []
  const view = mountSfc('components/editor/ItemsTab.vue', {
    ...props(), editorObjects: [{ id: 'KEY', name: 'Key', current_scene_id: 'LAB' }],
    onAddItem: id => events.push(id),
  }, dependencies)
  view.all().find(node => node.type === 'select').props.onChange({ target: { value: 'LAB' } })
  await settle()
  view.button('Add').props.onClick()
  assert.deepEqual(events, ['LAB'])
  view.app.unmount()
})

const draft = {
  name: 'Silk scarf', description: 'A silver-grey silk scarf with neatly rolled edges.',
  item_type: 'WEARABLE', is_portable: true, wearable_slots: ['Neck'], text_log_content: '',
  clothing: { category: 'clothing', layer: 3, coverage: ['torso'], opaque: true },
}
test('draft mapping keeps generated clothing and preserves manual technical fields', () => {
  const form = { entity_id: 'SCARF', effects_hp: 12, item_type: 'WEARABLE' }
  Object.assign(form, itemDraftFields(draft))
  assert.equal(form.name, draft.name)
  assert.equal(form.entity_id, 'SCARF')
  assert.equal(form.effects_hp, 12)
  assert.deepEqual(form.wearable_slots_input, ['Neck'])
  assert.deepEqual(form.clothing, draft.clothing)
  form.clothing.coverage.push('arms')
  form.wearable_slots_input.push('Back')
  assert.deepEqual(draft.clothing.coverage, ['torso'])
  assert.deepEqual(draft.wearable_slots, ['Neck'])
})

const editor = readFileSync(new URL('../src/views/AdventureEditorView.vue', import.meta.url), 'utf8')
const handlers = editor.slice(editor.indexOf('function openItemCreateDialog('), editor.indexOf('const showAddExistingItemModal'))
const handlerCode = ts.transpileModule(`return function fixture(ref, itemDraftFields, handleItemTypeSelected) {
  const showItemCreateDialog=ref(false), itemCreateInitialScene=ref(null), createEntitySceneId=ref(null), editForm=ref({});
  const debugData=ref({adventure:{start_scene_id:'START'}}), editorScenes=ref([{id:'START'},{id:'LAB'}]);
  const notices=[], addNotification=(...args)=>notices.push(args);
  ${handlers}
  return {openItemCreateDialog,reviewNewItem,showItemCreateDialog,itemCreateInitialScene,createEntitySceneId,editForm,notices};
}`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
test('editor review creates a local draft at the selected location without saving', () => {
  const selected = []
  const view = new Function(handlerCode)()(ref, itemDraftFields, type => selected.push(type))
  view.openItemCreateDialog(null)
  assert.equal(view.itemCreateInitialScene.value, 'START')
  view.reviewNewItem(draft, 'LAB')
  assert.deepEqual(selected, ['WEARABLE'])
  assert.equal(view.createEntitySceneId.value, 'LAB')
  assert.equal(view.editForm.value.name, draft.name)
  assert.equal(view.showItemCreateDialog.value, false)
})
test('a deleted location leaves the create dialog open and does not open review', () => {
  const selected = []
  const view = new Function(handlerCode)()(ref, itemDraftFields, type => selected.push(type))
  view.openItemCreateDialog('LAB')
  view.reviewNewItem(draft, 'DELETED')
  assert.equal(view.showItemCreateDialog.value, true)
  assert.deepEqual(selected, [])
  assert.equal(view.notices[0][1], 'error')
})

test('Items and the description dialog are wired to the editor review handler', () => {
  assert.match(editor.match(/<ItemsTab[\s\S]*?\/>/)[0], /@add-item="openItemCreateDialog"/)
  assert.match(editor.match(/<ItemCreateDialog[\s\S]*?\/>/)[0], /@draft="reviewNewItem"/)
})
