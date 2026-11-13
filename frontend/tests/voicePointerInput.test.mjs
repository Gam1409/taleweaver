import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createRenderer, h, ref } from 'vue'
import { voiceInputModule } from './voiceInputModule.mjs'

const tick = () => new Promise(resolve => setImmediate(resolve))
const renderer = createRenderer({ createElement: type => ({ type, children: [] }), createText: text => ({ text }), createComment: text => ({ text }), setText() {}, setElementText() {}, patchProp() {}, insert(node, parent) { parent.children.push(node) }, remove() {}, parentNode: () => null, nextSibling: () => null })
async function fixture(t) {
  const permissions = [], streams = [], contexts = [], calls = [], sent = [], captures = new Set()
  const window = new EventTarget(), sessionId = ref('A'), canSendInput = ref(true), inputText = ref('')
  const module = await voiceInputModule((...args) => { calls.push(args); return { text: 'Example speech' } })
  window.AudioContext = class {
    state = 'running'; destination = {}; closed = 0
    constructor() { this.processor = { connect() {}, disconnect() {} }; this.source = { connect() {}, disconnect() {} }; contexts.push(this) }
    createMediaStreamSource() { return this.source }
    createScriptProcessor() { return this.processor }
    close() { this.state = 'closed'; this.closed++; return Promise.resolve() }
  }
  const oldWindow = globalThis.window, oldNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator')
  globalThis.window = window
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { mediaDevices: { getUserMedia: () => new Promise(resolve => permissions.push(resolve)) } } })
  const target = { setPointerCapture: id => captures.add(id), hasPointerCapture: id => captures.has(id), releasePointerCapture: id => captures.delete(id) }
  let now = 1000, voice
  t.mock.method(Date, 'now', () => now)
  const app = renderer.createApp({ setup() { voice = module.useVoiceInput({ sessionId, canSendInput, inputText, onSend() { sent.push(inputText.value) } }); return () => h('div') } })
  app.mount({ children: [] })
  t.after(() => { app.unmount(); module.dispose(); globalThis.window = oldWindow; if (oldNavigator) Object.defineProperty(globalThis, 'navigator', oldNavigator); else delete globalThis.navigator })
  const down = (id = 1, extra = {}) => voice.handleMicButtonPointerDown({ pointerId: id, isPrimary: true, button: 0, currentTarget: target, preventDefault() {}, shiftKey: false, ...extra })
  const fire = (type, id = 1) => window.dispatchEvent(Object.assign(new Event(type), { pointerId: id }))
  async function grant() { const track = { stopped: 0, stop() { this.stopped++ } }; streams.push(track); permissions.at(-1)({ getTracks: () => [track] }); await tick(); return track }
  async function record() { down(); await grant(); contexts.at(-1).processor.onaudioprocess({ inputBuffer: { getChannelData: () => new Float32Array([0.3]) } }); now += 600 }
  return { voice, down, fire, grant, record, permissions, streams, contexts, calls, sent, captures, sessionId, canSendInput, app }
}

for (const cancel of ['pointercancel', 'lostpointercapture']) for (const phase of ['permission', 'recording']) test(`${cancel} during ${phase} discards speech and releases capture`, async t => {
  const f = await fixture(t)
  if (phase === 'permission') f.down()
  else await f.record()
  f.fire(cancel)
  if (phase === 'permission') await f.grant()
  await tick()
  assert.equal(f.streams[0].stopped, 1); assert.equal(f.captures.size, 0)
  assert.equal(f.voice.isRecording.value, false); assert.deepEqual(f.sent, []); assert.equal(f.calls.length, 0)
  if (phase === 'recording') assert.equal(f.contexts[0].closed, 1)
})
test('pointer release records once while compatibility mouse events do nothing', async t => {
  const f = await fixture(t)
  await f.record()
  f.fire('mouseup'); assert.equal(f.voice.isRecording.value, true)
  f.fire('pointerup'); f.fire('lostpointercapture'); f.fire('pointerup')
  await tick()
  assert.equal(f.calls.length, 1); assert.deepEqual(f.sent, ['Example speech']); assert.equal(f.captures.size, 0)
})
test('unrelated pointer releases and keyboard release do not end a held microphone', async t => {
  const f = await fixture(t)
  await f.record()
  f.down(2, { isPrimary: false }); f.fire('pointerup', 2)
  f.fire('keyup'); assert.equal(f.voice.isRecording.value, true)
  assert.equal(f.permissions.length, 1)
  f.fire('pointerup'); await tick()
  assert.equal(f.calls.length, 1)
})
test('right mouse and secondary touch do not start recording', async t => {
  const f = await fixture(t)
  f.down(1, { button: 2 }); f.down(2, { isPrimary: false })
  assert.equal(f.permissions.length, 0); assert.equal(f.captures.size, 0)
})
test('session change releases capture and stale pointer events cannot cancel the next capture', async t => {
  const f = await fixture(t)
  f.down(); f.sessionId.value = 'B'; await f.grant()
  f.down(2); await f.grant()
  f.fire('pointercancel', 1)
  assert.equal(f.voice.isRecording.value, true); assert.deepEqual([...f.captures], [2])
  f.fire('pointercancel', 2); assert.equal(f.streams[1].stopped, 1)
})
test('unmount and disabled input discard a held pointer before late permission', async t => {
  const f = await fixture(t)
  f.down(); f.canSendInput.value = false; await f.grant()
  assert.equal(f.streams[0].stopped, 1); assert.equal(f.captures.size, 0)
  f.canSendInput.value = true; f.down(2); f.app.unmount(); await f.grant()
  assert.equal(f.streams[1].stopped, 1); assert.equal(f.contexts.length, 0); assert.deepEqual(f.sent, [])
})
