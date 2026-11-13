import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'

const utility = ts.transpileModule(readFileSync(new URL('../src/utils/equipmentSlots.ts', import.meta.url), 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
const utilityUrl = `data:text/javascript;base64,${Buffer.from(utility).toString('base64')}`
async function component(name, active = '') {
  const { descriptor } = parse(readFileSync(new URL(`../src/components/game/${name}.vue`, import.meta.url), 'utf8'))
  const source = compileScript(descriptor, { id: name, inlineTemplate: true }).content.replace(/import[\s\S]*?from ['"]([^'"]+)['"];?/g, (statement, path) => {
    if (path === 'vue') return statement.replace(/['"]vue['"]/, `'${import.meta.resolve('vue')}'`)
    if (path === '@/utils/equipmentSlots') return statement.replace(/['"]@\/utils\/equipmentSlots['"]/, `'${utilityUrl}'`)
    if (path.endsWith('.vue')) return `const ${statement.match(/import (\w+)/)[1]} = { render: () => null };`
    return ''
  })
  const prefix = `import {ref} from '${import.meta.resolve('vue')}';
const maleSilhouette='male.svg',femaleSilhouette='female.png';
const useEquipmentHover=()=>({active:ref(${JSON.stringify(active)}),target:ref(${active ? "'body'" : 'null'}),style:ref({}),close(){}});`
  const code = ts.transpileModule(prefix + source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  return (await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default
}
async function render(ui, props) { const context = {}; const html = await renderToString(createSSRApp({ render: () => h(ui, props) }), context); return { html, tooltip: context.teleports?.body ?? '' } }

test('all four declared groups render without fabricating items and unknown groups are ignored', async () => {
  const ui = await component('EquipmentSilhouette')
  const keys = ['BodyVaginal', 'BodyAnal', 'BodyUterine', 'BodyPenile']
  const { html } = await render(ui, { equipment: {}, bodySlots: [...keys, 'NOT_A_REGION'] })
  assert.equal((html.match(/data-equipment-slot=/g) || []).length, 15)
  for (const key of keys) assert.match(html, new RegExp(`data-equipment-slot="${key}"`))
  assert.doesNotMatch(html, /NOT_A_REGION/)
  assert.equal((html.match(/data-slot-occupied="true"/g) || []).length, 0)
})

test('hover combines body conditions and the same canonical item states', async () => {
  const ui = await component('EquipmentSilhouette', 'Hands')
  const { tooltip, html } = await render(ui, {
    equipment: { Hands: [{ id: 'glove', name: 'Black glove', current_state: [{ dimension: 'fabric', detail: 'The cuff is torn.' }] }] },
    bodyConditions: { Hands: [{ id: 'wound', part: 'hand', detail: 'A recorded cut.', status: 'active' }] },
    itemConditions: { glove: [{ id: 'dirt', detail: 'Dust coats the glove.', status: 'active' }] },
  })
  assert.match(html, /data-slot-has-state="true"/)
  assert.match(tooltip, /Body state|Items/)
  assert.match(tooltip, /A recorded cut\.|Black glove|The cuff is torn\.|Dust coats the glove\./)
  for (const text of ['A recorded cut.', 'Black glove', 'The cuff is torn.', 'Dust coats the glove.']) assert.ok(tooltip.includes(text))
})

test('unconfirmed binding is visible as uncertain without inventing an occupied item', async () => {
  const ui = await component('EquipmentSilhouette', 'BodyUterine')
  const { html, tooltip } = await render(ui, { equipment: {}, bodySlots: ['BodyUterine'], unconfirmedBodySlots: ['BodyUterine'] })
  assert.match(html, /data-slot-has-state="true"/)
  assert.doesNotMatch(html, /data-slot-occupied="true"/)
  assert.match(tooltip, /confirmation/)
})

test('body state text remains escaped and does not imply unrecorded diagnoses', async () => {
  const ui = await component('EquipmentSilhouette', 'BodyUterine')
  const { tooltip } = await render(ui, { equipment: {}, bodySlots: ['BodyUterine'], bodyConditions: { BodyUterine: [{ id: 'known', detail: '<ScRiPt>source</ScRiPt>', status: 'active' }] } })
  assert.match(tooltip, /&lt;ScRiPt&gt;/)
  assert.doesNotMatch(tooltip, /<script\b|pregnant|healthy/i)
})
