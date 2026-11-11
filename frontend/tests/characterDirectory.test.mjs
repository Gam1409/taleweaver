import { test } from 'node:test'
import assert from 'node:assert/strict'
import { h } from 'vue'
import { mountSfc, settle } from './mountSfc.mjs'

function fixture(t, directoryOpen = true) {
  const selected = { id: 'RIN', name: 'Доктор Рин', description: 'Врач', image_url: '/rin.png' }
  const directory = {
    props: ['sessionId'], emits: ['select', 'close'],
    setup: (props, { emit }) => () => h('button', { onClick: () => emit('select', selected) }, props.sessionId),
  }
  const card = {
    props: ['sessionId', 'npc', 'stateRevision', 'busy'], emits: ['close', 'generate'],
    setup: (props, { emit }) => () => h('article', { ...props, onClose: () => emit('close'),
      onGenerate: () => emit('generate', { use_previous_image: true }) }, props.npc.name),
  }
  const requests = []
  const view = mountSfc('components/game/SessionNpcModals.vue', {
    sessionId: 'session', directoryOpen, npc: null, stateRevision: { turn: 42 }, busy: false, error: '', updated: false,
    onSelect: npc => { view.props.npc = npc },
    onCloseCard: () => { view.props.npc = null },
    onGenerate: options => requests.push(options),
  }, { './SessionCharactersModal.vue': { default: directory }, './NpcPortraitModal.vue': { default: card } })
  t.after(() => view.app.unmount())
  return { ...view, selected, requests }
}

test('Characters selection replaces the directory with the shared current-state card and close returns to the list', async t => {
  const view = fixture(t)
  assert.equal(view.all().filter(node => node.type === 'button').length, 1)
  view.button('session').props.onClick()
  await settle()
  assert.equal(view.all().filter(node => node.type === 'button').length, 0)
  const card = view.all().find(node => node.type === 'article')
  assert.equal(view.text(card), 'Доктор Рин')
  assert.deepEqual(card.props.npc, view.selected)
  assert.deepEqual(card.props.stateRevision, { turn: 42 })
  card.props.onGenerate()
  assert.deepEqual(view.requests, [{ use_previous_image: true }])
  card.props.onClose()
  await settle()
  assert.ok(view.button('session'))
  assert.equal(view.all().filter(node => node.type === 'article').length, 0)
})

test('opening the same card from a scene portrait does not open the directory on close', async t => {
  const view = fixture(t, false)
  view.props.npc = view.selected
  await settle()
  view.all().find(node => node.type === 'article').props.onClose()
  await settle()
  assert.equal(view.all().filter(node => ['article', 'button'].includes(node.type)).length, 0)
})
