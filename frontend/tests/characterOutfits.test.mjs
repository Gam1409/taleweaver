import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { parse, compileScript } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive } from 'vue'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const wardrobe = { allow_underwear: true, owned: [{ id: 'COAT', name: 'White coat', worn: true }] }
const result = { context: wardrobe, notes: [], draft: { appearance: null, outfit: [
  { item_id: 'BRA', name: 'Red bra', description: 'Red silk.', wearable_slots: ['Chest'], clothing: { layer: 0, coverage: ['torso'], underwear: true } },
  { name: 'Grey skirt', description: 'Wool with precise seams.', wearable_slots: ['Legs'], clothing: { layer: 2, coverage: ['pelvis', 'legs'] } },
] } }
function fixture(t) {
  const calls = [], changes = [], busy = []
  const source = readFileSync(new URL('../src/components/editor/CharacterOutfitGenerator.vue', import.meta.url), 'utf8')
    .replace('</script>', 'defineExpose({toggle,generate,brief,includeUnderwear,draft,items,selected,context,busy,error})\n</script>')
  const { descriptor } = parse(source)
  const code = ts.transpileModule(compileScript(descriptor, { id: 'existing-outfit-tests' }).content, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const service = Object.fromEntries(['loadCharacterOutfit', 'generateCharacterOutfit'].map(name => [name,
    (...args) => new Promise((resolve, reject) => calls.push({ name, args, resolve, reject })),
  ]))
  const module = { exports: {} }
  new Function('require', 'module', 'exports', code)(name => name === '@/services/characterOutfits' ? service
    : name === './NpcDraftItems.vue' ? { render: () => null } : require(name), module, module.exports)
  const component = module.exports.default
  component.render = () => null
  const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
    insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
  const props = reactive({ adventureId: 'A', targetType: 'npc', targetId: 'RIN', name: 'Rin', description: 'Dark hair.', character: 'Careful.', goal: 'Research.', inventoryIds: ['COAT', 'BRA'], contextVersion: '32' })
  let view
  const app = renderer.createApp({ render: () => h(component, { ...props, ref: instance => { view = instance },
    'onUpdate:modelValue': value => changes.push(value), onBusy: value => busy.push(value),
  }) })
  app.mount({})
  t.after(() => app.unmount())
  return { view, props, app, calls, changes, busy }
}
async function open(v) {
  v.view.toggle()
  v.calls[0].resolve(wardrobe)
  await new Promise(resolve => setImmediate(resolve))
}

test('opening clothing reads context without requesting a model or saving', async t => {
  const v = fixture(t)
  assert.equal(v.calls.length, 0)
  await open(v)
  assert.deepEqual(v.calls[0].args[0], { adventureId: 'A', targetType: 'npc', targetId: 'RIN' })
  assert.equal(v.view.context.owned[0].worn, true)
  assert.equal(v.calls.length, 1)
})

test('generation includes unsaved added inventory and emits only selected clothing for normal save', async t => {
  const v = fixture(t)
  await open(v)
  v.view.includeUnderwear = true
  const pending = v.view.generate()
  assert.deepEqual(v.calls[1].args[1].inventory_ids, ['COAT', 'BRA'])
  v.calls[1].resolve(structuredClone(result))
  await pending
  await nextTick()
  assert.equal(v.changes.at(-1).outfit.length, 2)
  v.view.selected = [false, true]
  await nextTick()
  assert.deepEqual(v.changes.at(-1).outfit.map(item => item.name), ['Grey skirt'])
  assert.equal(v.calls.length, 2)
})

test('changing the card discards stale suggestions without reloading known clothing per keystroke', async t => {
  const v = fixture(t)
  await open(v)
  const pending = v.view.generate()
  v.props.description = 'Edited physical appearance.'
  await nextTick()
  v.calls[1].resolve(structuredClone(result))
  await pending
  assert.equal(v.view.draft, null)
  assert.equal(v.changes.at(-1), null)
  assert.equal(v.calls.length, 2)
  assert.equal(v.view.context.owned[0].id, 'COAT')
})

test('changing the target ignores old completion and retains the newer context request busy state', async t => {
  const v = fixture(t)
  await open(v)
  v.view.includeUnderwear = true
  const pending = v.view.generate()
  v.props.targetId = 'MIKI'
  await nextTick()
  v.calls[1].resolve(structuredClone(result))
  await pending
  assert.equal(v.view.draft, null)
  assert.equal(v.view.busy, true)
  v.calls[2].resolve({ allow_underwear: false, owned: [] })
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(v.view.context.allow_underwear, false)
  assert.equal(v.view.includeUnderwear, false)
  assert.equal(v.view.busy, false)
})

test('failed generation remains retryable and preserves its author preferences', async t => {
  const v = fixture(t)
  await open(v)
  v.view.brief = 'Keep the coat.'
  const pending = v.view.generate()
  v.calls[1].reject(new Error('Model unavailable'))
  await pending
  assert.match(v.view.error, /Model unavailable/)
  assert.equal(v.view.brief, 'Keep the coat.')
  assert.equal(v.view.busy, false)
  assert.equal(v.view.draft, null)
})
