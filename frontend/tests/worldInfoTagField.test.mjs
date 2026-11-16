import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createRenderer, h, nextTick, ref } from 'vue'
import { TagField } from './worldInfoTagFieldModule.mjs'
const descendants = (node, type) => [node, ...(node.children ?? []).flatMap(child => descendants(child, type))].filter(value => value.type === type)
function mount(initial, limit = 12, suggestions = []) {
  const tags = ref([...initial]), changes = []
  const element = type => ({ type, props: {}, children: [], focus() {}, querySelectorAll(selector) { return descendants(this, selector) } })
  const renderer = createRenderer({
    createElement: element,
    createText: text => ({ type: 'text', text }), createComment: text => ({ type: 'comment', text }),
    setText: (node, text) => { node.text = text }, setElementText: (node, text) => { node.text = text },
    patchProp: (node, key, _previous, value) => { node.props[key] = value },
    insert(node, parent, anchor) { node.parent = parent; const index = parent.children.indexOf(anchor); parent.children.splice(index < 0 ? parent.children.length : index, 0, node) },
    remove(node) { const children = node.parent.children; children.splice(children.indexOf(node), 1) },
    parentNode: node => node.parent, nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1],
  })
  const root = element('root')
  const app = renderer.createApp({ render: () => h(TagField, { modelValue: tags.value, label: 'Exact tags', limit, suggestions, characterLimit: 48, 'onUpdate:modelValue': value => { tags.value = value; changes.push([...value]) } }) })
  app.mount(root)
  return { tags, changes, root, app }
}
test('editing one tag updates its draft on input without rewriting untouched tag identities', async t => {
  const original = ['#harbour', 'harbour history', 'trade,craft', 'harbour', 'line\r\nbreak\tlabel']
  const field = mount(original)
  t.after(() => field.app.unmount())
  assert.deepEqual(descendants(field.root, 'textarea').map(node => node.props.value), original)
  descendants(field.root, 'textarea')[0].props.onInput({ target: { value: '#changed harbour, label' } })
  assert.deepEqual(field.tags.value, ['#changed harbour, label', ...original.slice(1)])
  assert.deepEqual(field.changes, [['#changed harbour, label', ...original.slice(1)]])
  await nextTick()
  assert.equal(descendants(field.root, 'textarea')[0].props.value, '#changed harbour, label')
})
test('explicit tag add and remove emit array changes and enforce the saved tag count limit', async t => {
  const field = mount(['#harbour', 'harbour history'], 3)
  t.after(() => field.app.unmount())
  await descendants(field.root, 'button').at(-1).props.onClick()
  assert.deepEqual(field.tags.value, ['#harbour', 'harbour history', ''])
  assert.equal(descendants(field.root, 'button').at(-1).props.disabled, true)
  descendants(field.root, 'textarea').at(-1).props.onInput({ target: { value: 'trade,craft' } })
  await nextTick()
  descendants(field.root, 'button')[0].props.onClick()
  assert.deepEqual(field.tags.value, ['harbour history', 'trade,craft'])
  await nextTick()
  assert.equal(descendants(field.root, 'button').at(-1).props.disabled, false)
})
test('saved tag choices preserve exact identities including line endings', async t => {
  const raw = 'line\r\nbreak\tlabel', field = mount(['harbour'], 3, ['harbour', '#harbour', raw])
  t.after(() => field.app.unmount())
  assert.deepEqual(descendants(field.root, 'option').map(node => node.props.value), ['', '#harbour', raw])
  const target = { value: raw }
  descendants(field.root, 'select')[0].props.onChange({ target })
  assert.deepEqual(field.tags.value, ['harbour', raw])
  assert.equal(target.value, '')
})
