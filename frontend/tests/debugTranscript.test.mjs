import { test } from 'node:test'
import assert from 'node:assert/strict'
import { storyMessageModule } from './storyMessageModule.mjs'

const { visibleChatMessages, isStoryMessage, isReplayBoundary } = await import(storyMessageModule)
const history = [
  { id: 'story', role: 'assistant', content: 'Lina remembers the shared secret.' },
  { id: 'on', role: 'user', content: '/debug on' },
  { id: 'enabled', role: 'system', content: 'Enabled.' },
  { id: 'edit', role: 'user', content: '/debug npc_wardrobe LINA carry COAT', is_debug: true },
  { id: 'result', role: 'system', content: 'Changed.', is_debug: true },
  { id: 'off', role: 'user', content: '/debug off' },
  { id: 'disabled', role: 'system', content: 'Disabled.' },
  { id: 'next', role: 'user', content: 'I ask Lina a question.' },
  { id: 'door', role: 'system', content: 'The door opens.' },
  { id: 'answer', role: 'assistant', content: 'Lina replies.' },
  { id: 'timing', role: 'system', content: '[DEBUG: Performance] Timing only.' }
]

test('Debug off hides commands, legacy responses and diagnostics without changing raw history', () => {
  const before = structuredClone(history)
  assert.deepEqual(
    visibleChatMessages(history, false).map(message => message.id),
    ['story', 'next', 'door', 'answer']
  )
  assert.deepEqual(history, before)
  assert.equal(visibleChatMessages(history, false)[0], history[0])
})

test('Debug on restores the entire inspection transcript', () => {
  assert.deepEqual(visibleChatMessages(history, true), history)
})

test('a completed legacy Debug reply cannot hide later game events without a new user row', () => {
  const messages = [
    { role: 'user', content: '/debug on' },
    { role: 'system', content: 'Enabled.' },
    { role: 'system', content: 'The bridge opens.' },
    { role: 'assistant', content: 'Lina watches the bridge.' }
  ]
  assert.deepEqual(visibleChatMessages(messages, false), messages.slice(2))
})

test('quoted commands remain story text and explicit flags survive arbitrary wording', () => {
  const messages = [
    { role: 'user', content: 'Lina quoted "/debug on" while talking.' },
    { role: 'assistant', content: 'A diagnostic generated reply.', is_debug: true },
    { role: 'assistant', content: 'An ordinary answer.' }
  ]
  assert.deepEqual(visibleChatMessages(messages, false), [messages[0], messages[2]])
})

test('hidden state-changing commands still block regeneration across a world edit', () => {
  assert.equal(isReplayBoundary(history.find(message => message.id === 'edit')), true)
  assert.equal(isReplayBoundary(history.find(message => message.id === 'on')), false)
  assert.equal(isReplayBoundary(history.find(message => message.id === 'off')), false)
  assert.equal(isStoryMessage(history.find(message => message.id === 'edit')), false)
  assert.equal(isStoryMessage({ role: 'user', content: '/debug heal' }), false)
  assert.equal(
    isReplayBoundary({ role: 'user', content: 'A technical override.', is_debug: true }),
    true
  )
  assert.equal(
    isReplayBoundary({ role: 'assistant', content: 'Generated technical output.', is_debug: true }),
    true
  )
})
