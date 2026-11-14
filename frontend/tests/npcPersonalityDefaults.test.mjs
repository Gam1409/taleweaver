import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRenderer, h, nextTick, ref } from 'vue'
import { compileScript, parse } from '@vue/compiler-sfc'
import ts from 'typescript'

const { descriptor } = parse(readFileSync(new URL('../src/components/living-world/NpcPersonalityDefaults.vue', import.meta.url), 'utf8'))
const compiled = ts.transpileModule(compileScript(descriptor, { id: 'npc-personality-defaults', inlineTemplate: true }).content, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText.replace(/from ['"]vue['"]/g, `from '${import.meta.resolve('vue')}'`)
const component = (await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)).default
const descendants = node => [node, ...(node.children ?? []).flatMap(descendants)]
const text = node => [node.text ?? '', ...(node.children ?? []).map(text)].join('')
const settings = () => ({ mode: 'live', actor_ids: ['NPC'], max_active_npcs: 3, model_role: 'complex', max_output_tokens: 1200, max_input_chars: 24000, max_calls_per_turn: 8, memory_limit: 12, agent_steps: 0 })

function fixture(t, initial = settings()) {
  const value = ref(initial), changes = [], root = { children: [] }
  const renderer = createRenderer({
    createElement: tag => ({ tag, props: {}, children: [] }),
    createText: value => ({ text: value }), createComment: () => ({}),
    setText: (node, value) => { node.text = value },
    setElementText: (node, value) => { node.text = value; node.children = [] },
    patchProp: (node, key, _previous, next) => { node.props[key] = next },
    insert(node, parent, anchor) {
      if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1)
      node.parent = parent
      const index = parent.children.indexOf(anchor)
      parent.children.splice(index < 0 ? parent.children.length : index, 0, node)
    },
    remove(node) { node.parent.children.splice(node.parent.children.indexOf(node), 1) },
    parentNode: node => node.parent,
    nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1],
  })
  const app = renderer.createApp({ render: () => h(component, {
    modelValue: value.value, characters: [{ id: 'NPC', name: 'Lina' }],
    'onUpdate:modelValue': next => { changes.push(next); value.value = next },
  }) })
  app.mount(root)
  t.after(() => app.unmount())
  const checkbox = () => descendants(root).find(node => node.props?.name === 'npc-private-notebooks')
  return { value, changes, root, checkbox }
}

test('template notebook opt-in emits one draft update with an agent round and unchanged budget', async t => {
  const original = settings(), f = fixture(t, original)
  assert.equal(f.checkbox()?.props.checked, false)
  f.checkbox().props.onChange({ target: { checked: true } })
  await nextTick()
  assert.equal(f.changes.length, 1)
  assert.equal(f.value.value.notebook_enabled, true)
  assert.equal(f.value.value.agent_steps, 1)
  assert.equal(f.value.value.max_calls_per_turn, 8)
  assert.equal(original.notebook_enabled, undefined)
  assert.notEqual(f.value.value.actor_ids, original.actor_ids)
  assert.match(text(f.root), /16,000,000 UTF-8 bytes/)
  assert.match(text(f.root), /Undo or Chronicles restore/)
  assert.doesNotMatch(text(f.root), /Read-only agent rounds/)
})

test('template notebook controls retain two agent rounds and keep the off option unavailable', async t => {
  const f = fixture(t, { ...settings(), agent_steps: 2 })
  f.checkbox().props.onChange({ target: { checked: true } })
  await nextTick()
  assert.equal(f.value.value.agent_steps, 2)
  const off = descendants(f.root).filter(node => node.tag === 'select').at(-1).children.find(node => node.props?.value === 0)
  assert.equal(off.props.disabled, true)
  f.checkbox().props.onChange({ target: { checked: false } })
  await nextTick()
  assert.equal(f.value.value.notebook_enabled, false)
  assert.equal(f.value.value.agent_steps, 2)
})

test('new adventure defaults leave notebooks and tool rounds off', async t => {
  const f = fixture(t, null)
  assert.equal(f.checkbox(), undefined)
  descendants(f.root).find(node => node.tag === 'select').props.onChange({ target: { value: 'live' } })
  await nextTick()
  assert.equal(f.value.value.notebook_enabled, false)
  assert.equal(f.value.value.agent_steps, 0)
  assert.equal(f.checkbox().props.checked, false)
})
