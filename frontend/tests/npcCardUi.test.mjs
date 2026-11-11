import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createSSRApp, h, ref, reactive, effectScope, nextTick } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'

let sequence = 0
const read = name => readFileSync(new URL(`../src/components/game/${name}.vue`, import.meta.url), 'utf8')
async function component(name, inject = '') {
  const { descriptor } = parse(read(name))
  let source = compileScript(descriptor, { id: name, inlineTemplate: true }).content
  source = source.replace(/import[\s\S]*?from ['"]([^'"]+)['"];?/g, (statement, path) => {
    if (path === 'vue') return statement.replace(/['"]vue['"]/, `'${import.meta.resolve('vue')}'`)
    if (path.endsWith('.vue')) return `const ${statement.match(/import (\w+)/)[1]} = { render: () => null };`
    return ''
  })
  const code = ts.transpileModule(`${inject}\n${source}`, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  return (await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default
}
const render = (component, props) => renderToString(createSSRApp({ render: () => h(component, props) }))

test('emotion-only estimates do not fabricate relationship scores; text is escaped', async () => {
  const ui = await component('NpcNarrativeInsights')
  const html = await render(ui, { insights: { available: true, relationship: null, emotion: '<script>alarm</script>', evidence: '<img onerror=alert(1)>' } })
  assert.match(html, /No confirmed relationship estimate/)
  assert.doesNotMatch(html, /<dt|<script\b|<img\b/i)
  assert.match(html, /&lt;script&gt;/)
  const scores = await render(ui, { insights: { available: true, relationship: { trust: 12, affinity: -3, respect: 4, tension: 2 }, emotion: null } })
  assert.match(scores, /\+12/)
  assert.match(scores, /-3/)
  assert.doesNotMatch(scores, /Last observed emotion:/)
})

test('history tabs show general facts and empty-state without arbitrary private fields', async t => {
  const key = `__npcCard${sequence++}`
  globalThis[key] = ref({ id: 'mira', name: 'Mira', summary: [{ id: 'a', text: 'Helped at the gate', source: 'observed' }], entries: [{ id: 'g', category: 'background', text: 'Grew up by the river', source: 'observed' }], entry_count: 1, history_counts: { general: 1, shared: 1 }, inventory: ['SECRET_INVENTORY'], goals: ['PRIVATE_GOALS'], plans: 'HIDDEN_PLANS' })
  t.after(() => delete globalThis[key])
  const ui = await component('NpcJournalDetails', `const useNpcJournal = () => ({ details: globalThis['${key}'], loading: false, error: '', load: () => {} });
const useNpcCardSettings = () => ({ showState: {value:false} });
const setInterval = () => 0;`)
  const html = await render(ui, { sessionId: 's', npcId: 'mira' })
  assert.match(html, /Grew up by the river/)
  assert.doesNotMatch(html, /Helped at the gate/)
  assert.match(html, /role="tab"[^>]*aria-selected="true"/)
  assert.match(html, /role="tabpanel"/)
  assert.match(html, /History with your character/)
  assert.doesNotMatch(html, /SECRET_INVENTORY|PRIVATE_GOALS|HIDDEN_PLANS|<details[^>]*open/)
  globalThis[key].value = { entries: [], entry_count: 0 }
  assert.match(await render(ui, { sessionId: 's', npcId: 'mira' }), /No general history learned yet/)
})

test('changing characters resets portrait options and learned display; regenerated image wins', async t => {
  const key = `__npcProps${sequence++}`
  globalThis[key] = reactive({ sessionId: 's', npc: { id: 'first', name: 'Old', description: 'Stage description', image_url: '/stage.png' }, updated: false })
  t.after(() => delete globalThis[key])
  let source = read('NpcPortraitModal').match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
    .replace(/import[\s\S]*?from ['"][^'"]+['"];?/g, '')
    .replace(/const props = defineProps<[\s\S]*?>\(\)/, `const props = globalThis['${key}']`)
    .replace(/const emit = defineEmits<[\s\S]*?>\(\)/, 'const emit = () => {}')
  source = `import { computed, ref, watch, onScopeDispose as onBeforeUnmount } from '${import.meta.resolve('vue')}';
const document = {activeElement: null}; class HTMLElement {}; const onMounted = () => {};
export function setup() { ${source}; return { learnedCard, characterName, description, imageUrl, brokenImage, purpose, usePreviousImage, changeDescription }; }`
  const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  const { setup } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
  const scope = effectScope(), state = scope.run(setup)
  t.after(() => scope.stop())
  state.learnedCard.value = { name: 'Learned name', description: 'Learned description', image_url: '/learned.png' }
  assert.equal(state.characterName.value, 'Learned name')
  assert.equal(state.description.value, 'Learned description')
  state.learnedCard.value.description = ''
  assert.equal(state.description.value, '')
  assert.equal(state.imageUrl.value, '/learned.png')
  globalThis[key].updated = true
  assert.equal(state.imageUrl.value, '/stage.png')
  state.purpose.value = 'variation'
  state.changeDescription.value = 'Smile'
  state.brokenImage.value = '/stage.png'
  await nextTick()
  assert.equal(state.usePreviousImage.value, true)
  globalThis[key].npc = { id: 'second', name: 'New', description: '', image_url: null }
  await nextTick()
  assert.equal(state.learnedCard.value, null)
  assert.equal(state.characterName.value, 'New')
  assert.equal(state.brokenImage.value, '')
  assert.equal(state.purpose.value, 'repair')
  assert.equal(state.usePreviousImage.value, false)
  assert.equal(state.changeDescription.value, '')
})

test('display preference reflects nested reactive values and disables editing while saving', async () => {
  const ui = await component('NpcCardPreferences')
  const settings = { showState: ref(false), loaded: ref(true), saving: ref(false), error: ref(''), refresh: () => {}, setShowState: () => {} }
  const off = await render(ui, { settings })
  assert.doesNotMatch(off, /<input[^>]*checked|<input[^>]*disabled/)
  settings.showState.value = true
  settings.saving.value = true
  const on = await render(ui, { settings })
  assert.match(on, /<input[^>]*checked/)
  assert.match(on, /<input[^>]*disabled/)
  assert.match(on, /Updating display settings/)
})

test('history tabs support keyboard activation and reset for a different character or session', async t => {
  const key = `__npcHistory${sequence++}`
  globalThis[key] = reactive({ sessionId: 's1', npcId: 'mira' })
  t.after(() => delete globalThis[key])
  let source = read('NpcJournalDetails').match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
    .replace(/import[\s\S]*?from ['"][^'"]+['"];?/g, '')
    .replace(/const props = defineProps<[\s\S]*?>\(\)/, `const props = globalThis['${key}']`)
    .replace(/const emit = defineEmits<[\s\S]*?>\(\)/, 'const emit = () => {}')
  source = `import { computed, ref, watch, toRef, onScopeDispose as onBeforeUnmount } from '${import.meta.resolve('vue')}';
const useNpcJournal = () => ({ details: ref(null), loading: ref(false), error: ref(''), load: () => {} });
const useNpcCardSettings = () => ({ showState: ref(false) });
const setInterval = () => 0;
export function setup() { ${source}; return { history, navigateTabs, tabId, activeTab, navigateSections }; }`
  const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  const { setup } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
  const scope = effectScope(), state = scope.run(setup)
  t.after(() => scope.stop())
  let focused = '', prevented = 0
  const press = key => state.navigateTabs({ key, preventDefault: () => prevented++, currentTarget: { closest: () => ({ querySelector: selector => ({ focus: () => { focused = selector } }) }) } })
  press('ArrowRight')
  assert.equal(state.history.value, 'shared')
  assert.equal(focused, '[data-history="shared"]')
  press('ArrowRight')
  assert.equal(state.history.value, 'general')
  press('End')
  assert.equal(state.history.value, 'shared')
  press('Home')
  assert.equal(state.history.value, 'general')
  press('ArrowLeft')
  assert.equal(state.history.value, 'shared')
  press('Escape')
  assert.equal(prevented, 5)
  assert.equal(state.activeTab.value, 'state')
  state.navigateSections({ key: 'End', preventDefault: () => {}, currentTarget: { closest: () => ({ querySelector: () => ({ focus: () => {} }) }) } })
  assert.equal(state.activeTab.value, 'history')
  assert.equal(state.history.value, 'shared')
  globalThis[key].npcId = 'new-character'
  assert.equal(state.history.value, 'general')
  assert.equal(state.activeTab.value, 'state')
  state.history.value = 'shared'
  globalThis[key].sessionId = 's2'
  assert.equal(state.history.value, 'general')
  assert.match(state.tabId.value, /s2-new-character/)
})

test('current state shows confirmed facts without immersion-breaking diagnostics', async () => {
  const ui = await component('NpcCurrentState')
  const state = {
    availability: 'present', game_minute: 480,
    clothing: { status: 'available', items: [], detail_limited: false },
    conditions: { status: 'available', items: [{ id: 'wound', kind: 'injury', part: 'arm', status: 'treated', detail: '<script>Bandage</script>', last_changed_minute: 470 }] },
  }
  const observed = await render(ui, { state })
  assert.match(observed, /Treated|game minute 480/)
  assert.match(observed, /&lt;script&gt;Bandage&lt;\/script&gt;/)
  assert.doesNotMatch(observed, /<script\b/)
  const absent = await render(ui, { state: { ...state, availability: 'not_present' } })
  assert.doesNotMatch(absent, /not currently visible|Bandage|Treated/)
  const unknown = await render(ui, { state: { ...state, clothing: { status: 'unavailable', items: [] }, conditions: { status: 'unavailable', items: [] } } })
  assert.doesNotMatch(unknown, /Clothing details are not confirmed|Current physical conditions are not confirmed/)
  assert.doesNotMatch(unknown, /No known physical conditions recorded/)
})

test('equipment lists preserve partial placement and escape item text', async () => {
  const ui = await component('EquipmentList')
  const item = { id: 'coat', name: '<b>Coat</b>', image_url: '/coat.png', layer: 2, description: '<script>detail</script>', uncovered_regions: ['torso'] }
  const html = await render(ui, { items: [item] })
  assert.match(html, /Partially displaced/)
  assert.match(html, /&lt;b&gt;Coat&lt;\/b&gt;/)
  assert.doesNotMatch(html, /<script\b|<b>/)
  const missing = await render(ui, { items: [{ ...item, image_url: null, uncovered_regions: [] }] })
  assert.doesNotMatch(missing, /<img\b|Partially displaced/)
})

test('equipment icons use canonical images at 14 px with a missing-image fallback', async () => {
  const ui = await component('EquipmentItemIcon', 'const getImageUrl = path => path;')
  const html = await render(ui, { item: { id: 'coat', name: '<script>Coat</script>', image_url: '/coat.png' } })
  assert.match(html, /src="\/coat.png"/)
  assert.match(html, /h-3\.5 w-3\.5/)
  assert.doesNotMatch(html, /<script\b/)
  const missing = await render(ui, { item: { id: 'coat', name: 'Coat', image_url: null } })
  assert.doesNotMatch(missing, /<img\b/)
  assert.match(missing, /ra-vest/)
})

test('silhouettes show overlapping layers and only occupied unlabelled body positions', async t => {
  const path = new URL('../src/utils/equipmentSlots.ts', import.meta.url)
  const utility = ts.transpileModule(readFileSync(path, 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  const key = `__equipmentSlots${sequence++}`
  globalThis[key] = await import(`data:text/javascript;base64,${Buffer.from(utility).toString('base64')}`)
  t.after(() => delete globalThis[key])
  const ui = await component('EquipmentSilhouette', `
import { ref } from '${import.meta.resolve('vue')}';
const {EQUIPMENT_SLOTS, BODY_ITEM_SLOTS} = globalThis['${key}'];
const maleSilhouette='male.svg', femaleSilhouette='female.png';
const useEquipmentHover=()=>({active:ref(''),target:ref(null),style:ref({}),close:()=>{}});`)
  const empty = await render(ui, { equipment: {}, variant: 'female', class: 'parent-width' })
  assert.match(empty, /data-silhouette="female"/)
  assert.match(empty, /src="female.png"/)
  assert.match(empty, /parent-width/)
  assert.equal((empty.match(/data-equipment-slot=/g) || []).length, 11)
  assert.doesNotMatch(empty, /BodyAnal|BodyVaginal|NSFW/)
  const layered = await render(ui, { variant: 'male', equipment: {
    Feet: [{ id: 'boot', name: 'Boots' }, { id: 'sock', name: '<b>Socks</b>' }],
    BodyAnal: [{ id: 'sensor', name: 'Medical sensor' }],
  } })
  assert.match(layered, /src="male.svg"/)
  assert.equal((layered.match(/data-equipment-slot=/g) || []).length, 12)
  assert.match(layered, /aria-label="Feet: Boots: &lt;b&gt;Socks&lt;\/b&gt;"/)
  assert.match(layered, /aria-label="Medical sensor"/)
  assert.doesNotMatch(layered, /BodyVaginal|>Anal<|>Vaginal<|<b>/)
})

test('missing portrait offers generation next to the avatar before advanced options', async () => {
  const ui = await component('NpcPortraitModal', `const document = { activeElement: null }; class HTMLElement {};
const X = { render: () => null }, ImagePlus = X, Loader2 = X;
const getOriginalImageUrl = path => path;`)
  const empty = await render(ui, { npc: { id: 'mira', name: 'Mira', description: '', image_url: null }, busy: false, error: '', updated: false })
  assert.ok(empty.indexOf('Generate portrait') < empty.indexOf('Portrait options'))
  const existing = await render(ui, { npc: { id: 'mira', name: 'Mira', description: '', image_url: '/portrait.png' }, busy: false, error: '', updated: false })
  assert.doesNotMatch(existing, /Generate portrait/)
  assert.match(existing, /Regenerate portrait/)
})
