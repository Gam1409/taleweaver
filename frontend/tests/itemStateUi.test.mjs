import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { parse, compileScript } from '@vue/compiler-sfc'
import ts from 'typescript'
const snapshotCode = ts.transpileModule(readFileSync(new URL('../src/utils/conditionSnapshot.ts', import.meta.url), 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
const snapshotUrl = `data:text/javascript;base64,${Buffer.from(snapshotCode).toString('base64')}`

async function component(name) {
  const { descriptor } = parse(readFileSync(new URL(`../src/components/game/${name}.vue`, import.meta.url), 'utf8'))
  let source = compileScript(descriptor, { id: name, inlineTemplate: true }).content
  source = source.replace(/import[\s\S]*?from ['"]([^'"]+)['"];?/g, (statement, path) => {
    if (path === 'vue') return statement.replace(/['"]vue['"]/, `'${import.meta.resolve('vue')}'`)
    if (path === '@/utils/conditionSnapshot') return statement.replace(/['"]@\/utils\/conditionSnapshot['"]/, `'${snapshotUrl}'`)
    if (path.endsWith('.vue')) return `const ${statement.match(/import (\w+)/)[1]} = { render: () => null };`
    return ''
  })
  const code = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  return (await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)).default
}
const render = (component, props) => renderToString(createSSRApp({ render: () => h(component, props) }))

test('item properties have a label on NPC cards and current values on equipment lists', async () => {
  const card = await component('NpcCurrentState')
  const html = await render(card, { state: {
    availability: 'present', clothing: { items: [] },
    conditions: { items: [{ id: 'state1', kind: 'item_state', part: 'form', status: 'active', detail: 'The coat is crumpled.' }] },
  } })
  assert.match(html, /Item state · form/)
  assert.match(html, /The coat is crumpled/)
  const list = await component('EquipmentList')
  for (const tag of ['script', 'SCRIPT', 'ScRiPt']) {
    const equipment = await render(list, { items: [{ id: 'coat', name: 'Coat', current_state: [
      { dimension: 'form', detail: `Crumpled <${tag}>not executable</${tag}>.` },
    ] }] })
    assert.ok(equipment.includes(`Crumpled &lt;${tag}&gt;`))
    assert.doesNotMatch(equipment, /<script\b/i)
  }
})

test('equipment text escapes tags with attributes as well as mixed-case tag names', async () => {
  const list = await component('EquipmentList')
  const html = await render(list, { items: [{ id: 'coat', name: '<b onclick="window.executed=true">Coat</b>', current_state: [{ dimension: 'form', detail: '<ScRiPt>not executable</ScRiPt>' }] }] })
  assert.match(html, /&lt;b onclick=/)
  assert.doesNotMatch(html, /<script\b|<b\b/i)
})
