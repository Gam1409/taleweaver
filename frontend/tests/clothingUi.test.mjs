import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'

const read = path => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')
const moduleFor = async source => {
  const code = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
    .replaceAll('from "vue"', `from '${import.meta.resolve('vue')}'`).replaceAll("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  return import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
}
async function component(path) {
  const { descriptor } = parse(read(path))
  return (await moduleFor(compileScript(descriptor, { id: path, inlineTemplate: true }).content)).default
}
const render = (component, props) => renderToString(createSSRApp({ render: () => h(component, props) }))
const clothing = await component('components/game/AppearanceAndClothing.vue')
const setting = await component('components/create-adventure/AdventureClothingSettings.vue')
const garment = (item_id, layer, extra = {}) => ({ item_id, layer, name: item_id, description: '', visible: true, underwear: false, ...extra })

test('player clothing renders neutral appearance and own outer/covered layers without inventory or actions', async () => {
  const html = await render(clothing, { clothing: {
    appearance: { age_years: 25, hair: 'Short black hair', eyes: 'Brown', build: 'Tall', features: 'A small cheek scar', private_goal: 'SECRET_GOAL' },
    worn: [garment('shirt', 1, { visible: false }), garment('coat', 3), garment('undershirt', 0, { underwear: true, visible: false })],
    inventory: ['SECRET_ITEM'],
  } })
  assert.match(html, /25 years|Short black hair/)
  assert.match(html, /A small cheek scar/)
  assert.ok(html.indexOf('coat') < html.indexOf('shirt'))
  assert.match(html, /Underlayers/)
  assert.match(html, /Covered/)
  assert.doesNotMatch(html, /SECRET_GOAL|SECRET_ITEM|<button|<input/)
})

test('general mode payload shows only supplied outfit and never invents absent underlayers or age', async () => {
  const html = await render(clothing, { clothing: { appearance: { age_years: null, hair: '', eyes: '', build: '', features: '' }, worn: [garment('Raincoat', 3)], detail_limited: true } })
  assert.match(html, /General outfit/)
  assert.match(html, /Raincoat/)
  assert.doesNotMatch(html, /Underlayers|years/)
  const empty = await render(clothing, { clothing: null })
  assert.match(empty, /Appearance details will appear/)
  assert.match(empty, /No worn clothing details recorded yet/)
})

test('long outfits collapse and garment text is escaped', async () => {
  const html = await render(clothing, { clothing: { appearance: { age_years: null }, worn: Array.from({ length: 8 }, (_, i) => garment(`g${i}`, i % 5, { name: '<script>alert(1)</script>', description: '<img onerror=evil()>' })) } })
  assert.match(html, /<details/)
  assert.match(html, /Worn clothing · 8/)
  assert.doesNotMatch(html, /<details[^>]*open|<script>|<img /)
  assert.match(html, /&lt;script&gt;/)
})

test('adult clothing preference is a separate default-off setting', async () => {
  const off = await render(setting, { modelValue: false })
  assert.match(off, /Mature content/)
  assert.match(off, /Off: general outfits/)
  assert.doesNotMatch(off, /<input[^>]*checked|NPC state|mature_themes/)
  assert.match(await render(setting, { modelValue: true }), /<input[^>]*checked/)
})

test('creation sends the independent preference in both modes and clears it outside VN', async () => {
  const view = read('views/CreateAdventureView.vue')
  const formSource = view.slice(view.indexOf('const form = ref('), view.indexOf('const sourceAdventure ='))
  const createSource = view.slice(view.indexOf('async function handleCreate()'), view.indexOf('async function handleSuggestStoryIdea()'))
  const fixture = await moduleFor(`import {ref} from 'vue';
${formSource}
const calls = [], api = {createAdventure: async payload => calls.push(payload)}, router = {push: () => {}};
const generatorMode = ref('simple'), isCoverMode = ref(false), sourceAdventure = ref(null), isGenerating = ref(false), errorMsg = ref(''), imageStyles = ref([]), tones = ref([]), coverSourceId = ref('');
${createSource}
export { form, calls, generatorMode, handleCreate }`)
  assert.equal(fixture.form.value.detailed_clothing, false)
  assert.equal(fixture.form.value.show_npc_state, false)
  Object.assign(fixture.form.value, { title: 'The station', storyIdea: 'Adults meet at a station.', rule_enforcement_mode: 'vn', detailed_clothing: true, show_npc_state: false })
  await fixture.handleCreate()
  assert.equal(fixture.calls[0].detailed_clothing, true)
  assert.equal(fixture.calls[0].show_npc_state, false)
  fixture.generatorMode.value = 'advanced'
  fixture.form.value.detailed_clothing = false
  fixture.form.value.show_npc_state = true
  await fixture.handleCreate()
  assert.equal(fixture.calls[1].detailed_clothing, false)
  assert.equal(fixture.calls[1].show_npc_state, true)
  fixture.form.value.detailed_clothing = true
  fixture.form.value.rule_enforcement_mode = 'rpg'
  await fixture.handleCreate()
  assert.equal(fixture.calls[2].detailed_clothing, false)
})

test('VN opens Appearance without resetting an inventory tab on ordinary sheet updates', async () => {
  const source = read('components/game/CharacterSheetModal.vue')
  const initialization = source.slice(source.indexOf('const activeTab ='), source.indexOf('const showBio ='))
  const fixture = await moduleFor(`import { ref, reactive, watch, effectScope, nextTick } from 'vue';
const props = reactive({open:true,sheet:{rule_enforcement_mode:'vn',clothing:null}}), scope=effectScope();
const activeTab = scope.run(() => { ${initialization}; return activeTab });
export {props,activeTab,scope,nextTick};`)
  try {
    assert.equal(fixture.activeTab.value, 'appearance')
    fixture.activeTab.value = 'inventory'
    fixture.props.sheet = { rule_enforcement_mode: 'vn', clothing: null }
    await fixture.nextTick()
    assert.equal(fixture.activeTab.value, 'inventory')
    fixture.props.open = false
    await fixture.nextTick()
    fixture.props.open = true
    await fixture.nextTick()
    assert.equal(fixture.activeTab.value, 'appearance')
    fixture.props.sheet.rule_enforcement_mode = 'rpg'
    await fixture.nextTick()
    assert.equal(fixture.activeTab.value, 'inventory')
  } finally { fixture.scope.stop() }
})
