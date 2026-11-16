import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive } from 'vue'
import ts from 'typescript'
import { mountSfc, settle } from './mountSfc.mjs'
import { uuidModule } from './uuidModule.mjs'

const require = createRequire(import.meta.url)
const uuid = await import(uuidModule)
const sample = () => ({
  name: 'Rin', description: 'A careful doctor.', age_years: 32,
  items: [{ name: 'Coat', clothing: { layer: 3 } }, { name: 'Bra', clothing: { layer: 0, underwear: true } }, { name: 'Key', clothing: null }],
})
function fixture(t) {
  const calls = [], created = [], closes = []
  const source = readFileSync(new URL('../src/components/editor/NpcCreateDialog.vue', import.meta.url), 'utf8')
    .replace('</script>', 'defineExpose({generate,save,brief,age,includeUnderwear,includeClothing,draft,selected,busy,saving,error,canSave,sceneId})\n</script>')
  const { descriptor } = parse(source)
  const compiled = compileScript(descriptor, { id: 'npc-create-tests' }).content
  const code = ts.transpileModule(compiled, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  const service = Object.fromEntries(['generateNpcDraft', 'createNpcWithItems'].map(name => [name,
    (...args) => new Promise((resolve, reject) => calls.push({ name, args, resolve, reject })),
  ]))
  const module = { exports: {} }
  new Function('require', 'module', 'exports', code)(name => {
    if (name === '@/services/npcCreation') return service
    if (name === '@/composables/useDialogFocus') return { useDialogFocus() {} }
    if (name === '@/utils/uuid') return uuid
    if (name === './NpcDraftReview.vue') return { render: () => null }
    return require(name)
  }, module, module.exports)
  const component = module.exports.default
  component.render = () => null
  const renderer = createRenderer({
    createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
    insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {},
    parentNode: () => null, nextSibling: () => null,
  })
  const props = reactive({ adventureId: 'A', scenes: [{ id: 'LAB' }], innerClothingEnabled: true })
  let view
  const app = renderer.createApp({ render: () => h(component, { ...props,
    ref: instance => { view = instance }, onCreated: id => created.push(id), onClose: () => closes.push(true),
  }) })
  app.mount({})
  t.after(() => app.unmount())
  view.brief = 'A reserved doctor in a white coat.'
  return { view, props, calls, created, closes, app }
}

test('New is available with an empty NPC list and emits the generation action', async () => {
  const actions = []
  const v = mountSfc('components/editor/InhabitantsTab.vue', {
    form: {}, adventure: {}, debugData: {}, editorNpcs: [], editorScenes: [],
    isBatchGenerating: {}, isQuickGenerating: {}, activeMenuId: null,
    ruleEnforcementMode: 'vn', visualsCacheVersion: 0, onNewNpc: () => actions.push('new'),
  }, { '@/utils/game_icons': { getItemIcon: () => '' }, '@/utils/editor_utils': { hasAnyScript: () => false } })
  v.button('New').props.onClick()
  await settle()
  assert.deepEqual(actions, ['new'])
  v.app.unmount()
})

test('generation never publishes until explicit save; unchecked items are omitted', async t => {
  const v = fixture(t)
  v.view.age = 32
  v.view.includeUnderwear = true
  const generating = v.view.generate()
  assert.equal(v.calls[0].name, 'generateNpcDraft')
  assert.equal(v.calls[0].args[1].include_underwear, true)
  v.calls[0].resolve(sample())
  await generating
  assert.equal(v.calls.length, 1)
  v.view.selected = [true, false, true]
  const saving = v.view.save()
  assert.equal(v.calls[1].name, 'createNpcWithItems')
  assert.deepEqual(v.calls[1].args[2].items.map(item => item.name), ['Coat', 'Key'])
  v.calls[1].resolve({ npc_id: 'NPC_A' })
  await saving
  assert.deepEqual(v.created, ['NPC_A'])
})

test('failed publication preserves the draft and reuses its creation key on retry', async t => {
  const v = fixture(t)
  v.view.draft = sample()
  v.view.selected = [true, true, true]
  const first = v.view.save()
  v.calls[0].reject(new Error('Could not save'))
  await first
  assert.equal(v.view.draft.name, 'Rin')
  assert.match(v.view.error, /Could not save/)
  const retry = v.view.save()
  assert.equal(v.calls[0].args[3], v.calls[1].args[3])
  v.calls[1].resolve({ npc_id: 'NPC_A' })
  await retry
  assert.deepEqual(v.created, ['NPC_A'])
})

test('changing the scene ignores a late draft without releasing a newer request', async t => {
  const v = fixture(t)
  const old = v.view.generate()
  v.props.scenes = [{ id: 'HALL' }]
  await nextTick()
  const current = v.view.generate()
  v.calls[0].resolve(sample())
  await old
  assert.equal(v.view.draft, null)
  assert.equal(v.view.busy, true)
  v.calls[1].resolve({ ...sample(), name: 'Hall doctor' })
  await current
  assert.equal(v.view.draft.name, 'Hall doctor')
})

test('unknown/minor age and disabled settings prevent saving selected inner layers', async t => {
  const v = fixture(t)
  v.view.draft = { ...sample(), age_years: null }
  v.view.selected = [true, true, true]
  assert.equal(v.view.canSave, false)
  await v.view.save()
  assert.equal(v.calls.length, 0)
  v.view.selected = [true, false, true]
  assert.equal(v.view.canSave, true)
  v.props.scenes = []
  await nextTick()
  assert.equal(v.view.canSave, false)
})

test('disabling clothing clears the optional underwear request and old draft', async t => {
  const v = fixture(t)
  v.view.age = 32
  v.view.includeUnderwear = true
  v.view.draft = sample()
  v.view.includeClothing = false
  assert.equal(v.view.includeUnderwear, false)
  assert.equal(v.view.draft, null)
})

test('switching adventures closes the dialog and ignores old model completion', async t => {
  const v = fixture(t)
  const pending = v.view.generate()
  v.props.adventureId = 'B'
  await nextTick()
  v.calls[0].resolve(sample())
  await pending
  assert.equal(v.view.draft, null)
  assert.equal(v.closes.length, 1)
  assert.deepEqual(v.created, [])
})
