import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createRenderer, h, nextTick, ref } from 'vue'
import { voiceInputModule } from './voiceInputModule.mjs'
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no }); return { promise, resolve, reject } }
const flush = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)) }
const renderer = createRenderer({ createElement: type => ({ type, children: [] }), createText: text => ({ text }), createComment: text => ({ text }), setText() {}, setElementText() {}, patchProp() {}, insert(node, parent) { parent.children.push(node) }, remove() {}, parentNode: () => null, nextSibling: () => null })
async function fixture(t, transcribe = async () => ({ text: 'spoken action' })) {
  const permissions = [], contexts = [], streams = [], calls = [], sent = []
  const module = await voiceInputModule((...args) => { calls.push(args); return transcribe(...args) })
  const window = new EventTarget()
  window.AudioContext = class {
    state = 'running'; closed = 0; destination = {}
    constructor() { this.source = { disconnected: 0, connect() {}, disconnect() { this.disconnected++ } }; this.processor = { disconnected: 0, connect() {}, disconnect() { this.disconnected++ } }; contexts.push(this) }
    createMediaStreamSource() { return this.source }
    createScriptProcessor() { return this.processor }
    close() { this.state = 'closed'; this.closed++; return Promise.resolve() }
  }
  t.mock.method(console, 'error', () => {})
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
  Object.defineProperty(globalThis, 'window', { configurable: true, value: window })
  const navigator = { mediaDevices: { getUserMedia() { const request = deferred(); permissions.push(request); return request.promise } } }
  const previousNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator')
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: navigator })
  let now = 1000
  t.mock.method(Date, 'now', () => now)
  const sessionId = ref('A'), canSendInput = ref(true), inputText = ref('')
  let voice
  const app = renderer.createApp({ setup() { voice = module.useVoiceInput({ sessionId, canSendInput, inputText, onSend() { sent.push({ session: sessionId.value, text: inputText.value }); inputText.value = '' } }); return () => h('div') } })
  app.mount({ children: [] })
  t.after(() => { app.unmount(); module.dispose(); if (previousNavigator) Object.defineProperty(globalThis, 'navigator', previousNavigator); else delete globalThis.navigator; if (previousWindow) Object.defineProperty(globalThis, 'window', previousWindow); else delete globalThis.window })
  function grant(index = permissions.length - 1) { const track = { stopped: 0, stop() { this.stopped++ } }, stream = { track, getTracks: () => [track] }; streams.push(stream); permissions[index].resolve(stream); return stream }
  async function record(prefix = false) {
    voice.handleMicButtonPointerDown({ button: 0, isPrimary: true, pointerId: 1, currentTarget: {}, preventDefault() {}, shiftKey: prefix })
    const stream = grant(); await flush()
    contexts.at(-1).processor.onaudioprocess({ inputBuffer: { getChannelData: () => new Float32Array([0.25, -0.5]) } })
    now += 600
    return stream
  }
  return { voice, sessionId, canSendInput, inputText, permissions, contexts, streams, calls, sent, window, app, grant, record, advance: value => { now += value } }
}
test('a late transcription cannot append or autosend another session draft', async t => {
  const result = deferred(), f = await fixture(t, () => result.promise)
  await f.record()
  const stopping = f.voice.stopVoiceRecording(); await flush()
  f.sessionId.value = 'B'; f.inputText.value = 'New-session draft'
  result.resolve({ text: 'Old-session spoken action' }); await stopping
  assert.equal(f.inputText.value, 'New-session draft')
  assert.deepEqual(f.sent, [])
  assert.equal(f.calls[0][1]?.aborted, true)
})
test('returning to the same session does not revive its old transcription', async t => {
  const result = deferred(), f = await fixture(t, () => result.promise)
  await f.record(); const stopping = f.voice.stopVoiceRecording(); await flush()
  f.sessionId.value = 'B'; f.sessionId.value = 'A'; f.inputText.value = 'A new draft'
  result.resolve({ text: 'stale' }); await stopping
  assert.deepEqual(f.sent, []); assert.equal(f.inputText.value, 'A new draft')
})
test('permission granted after release never activates a late recording', async t => {
  const f = await fixture(t)
  f.voice.handleMicButtonPointerDown({ button: 0, isPrimary: true, pointerId: 1, currentTarget: {}, preventDefault() {}, shiftKey: false })
  f.window.dispatchEvent(Object.assign(new Event('pointerup'), { pointerId: 1 }))
  const stream = f.grant(); await flush()
  assert.equal(stream.track.stopped, 1); assert.equal(f.contexts.length, 0)
  assert.equal(f.voice.isRecording.value, false); assert.equal(f.calls.length, 0)
})
for (const phase of ['permission', 'recording', 'transcription']) for (const reason of ['session', 'unmount']) test(`${reason} cancels voice ${phase} without submitting its content`, async t => {
  const result = deferred(), f = await fixture(t, () => result.promise)
  let stream, stopping
  if (phase === 'permission') f.voice.handleMicButtonPointerDown({ button: 0, isPrimary: true, pointerId: 1, currentTarget: {}, preventDefault() {}, shiftKey: false })
  else stream = await f.record()
  if (phase === 'transcription') { stopping = f.voice.stopVoiceRecording(); await flush() }
  if (reason === 'session') f.sessionId.value = 'B'
  else f.app.unmount()
  if (phase === 'permission') stream = f.grant()
  result.resolve({ text: 'stale' }); await stopping; await flush()
  assert.equal(stream.track.stopped, 1)
  assert.equal(f.voice.isRecording.value, false); assert.equal(f.voice.isTranscribing.value, false)
  assert.deepEqual(f.sent, [])
  if (phase !== 'transcription') assert.equal(f.calls.length, 0)
  if (phase !== 'permission') { assert.equal(f.contexts[0].closed, 1); assert.equal(f.contexts[0].processor.disconnected, 1); assert.equal(f.contexts[0].source.disconnected, 1); assert.equal(f.contexts[0].processor.onaudioprocess, null) }
})
test('a stale completion cannot clear a newer session transcription state', async t => {
  const old = deferred(), current = deferred(); let count = 0
  const f = await fixture(t, () => ++count === 1 ? old.promise : current.promise)
  await f.record(); const oldStop = f.voice.stopVoiceRecording(); await flush()
  f.sessionId.value = 'B'
  await f.record(); const newStop = f.voice.stopVoiceRecording(); await flush()
  old.resolve({ text: 'old' }); await oldStop
  assert.equal(f.voice.isTranscribing.value, true); assert.deepEqual(f.sent, [])
  current.resolve({ text: 'new' }); await newStop
  assert.deepEqual(f.sent, [{ session: 'B', text: 'new' }])
})
test('editing a draft while transcription is pending prevents stale autosend even after restoring the text', async t => {
  const result = deferred(), f = await fixture(t, () => result.promise)
  f.inputText.value = 'Keep this draft'
  await f.record(); const stopping = f.voice.stopVoiceRecording(); await flush()
  f.inputText.value = 'Changed'; f.inputText.value = 'Keep this draft'
  result.resolve({ text: 'stale' }); await stopping
  assert.equal(f.inputText.value, 'Keep this draft'); assert.deepEqual(f.sent, [])
})
test('losing send capability cancels the old request even if input becomes available again', async t => {
  const result = deferred(), f = await fixture(t, () => result.promise)
  await f.record(); const stopping = f.voice.stopVoiceRecording(); await flush()
  f.canSendInput.value = false; f.canSendInput.value = true
  result.resolve({ text: 'stale' }); await stopping
  assert.deepEqual(f.sent, []); assert.equal(f.calls[0][1]?.aborted, true)
})
test('unchanged-session voice input keeps draft merging, captured say prefix and WAV encoding', async t => {
  const f = await fixture(t)
  f.inputText.value = 'Existing draft'
  await f.record(true); await f.voice.stopVoiceRecording()
  assert.deepEqual(f.sent, [{ session: 'A', text: 'Existing draft /say spoken action' }])
  const blob = f.calls[0][0], data = new DataView(await blob.arrayBuffer())
  assert.equal(blob.type, 'audio/wav'); assert.equal(data.getUint32(24, true), 16000)
  assert.equal(data.getUint16(22, true), 1); assert.equal(data.getUint16(34, true), 16)
  assert.equal(data.getUint32(40, true), 4); assert.equal(f.voice.isTranscribing.value, false)
})
test('draft edits made while recording are included when that recording is released', async t => {
  const f = await fixture(t)
  await f.record()
  f.inputText.value = 'Typed while recording'
  await f.voice.stopVoiceRecording()
  assert.deepEqual(f.sent, [{ session: 'A', text: 'Typed while recording spoken action' }])
})
for (const code of ['KeyV', 'KeyB', 'KeyT']) test(`${code} retains keyboard push-to-talk and its say-prefix behavior`, async t => {
  const f = await fixture(t)
  const keyboard = (type, key) => { const event = new Event(type, { cancelable: true }); Object.assign(event, { code: key, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false }); f.window.dispatchEvent(event) }
  keyboard('keydown', code)
  f.grant(); await flush()
  keyboard('keydown', code)
  assert.equal(f.permissions.length, 1)
  f.contexts[0].processor.onaudioprocess({ inputBuffer: { getChannelData: () => new Float32Array([0.2]) } })
  f.advance(600)
  keyboard('keyup', 'KeyX'); assert.equal(f.voice.isRecording.value, true)
  keyboard('keyup', code); await flush()
  assert.deepEqual(f.sent, [{ session: 'A', text: code === 'KeyV' ? 'spoken action' : '/say spoken action' }])
})
test('window blur discards recording and a short click submits no transcription', async t => {
  const f = await fixture(t)
  await f.record(); f.window.dispatchEvent(new Event('blur')); await flush()
  assert.equal(f.streams[0].track.stopped, 1); assert.equal(f.calls.length, 0)
  const starting = f.voice.startVoiceRecording(); f.grant(); await starting
  await f.voice.stopVoiceRecording()
  assert.equal(f.calls.length, 0); assert.equal(f.voice.isRecording.value, false)
})
test('pending permission cannot create duplicate microphone requests and failures permit a fresh capture', async t => {
  const f = await fixture(t)
  const first = f.voice.startVoiceRecording(), duplicate = f.voice.startVoiceRecording()
  assert.equal(f.permissions.length, 1)
  f.permissions[0].reject(new DOMException('Denied', 'NotAllowedError'))
  await first; await duplicate
  const next = f.voice.startVoiceRecording(); const stream = f.grant(); await next
  assert.equal(f.voice.isRecording.value, true)
  f.app.unmount(); assert.equal(stream.track.stopped, 1)
})
test('a held-key repeat cannot restart the old recording in a new session', async t => {
  const f = await fixture(t)
  const keydown = repeat => { const event = new Event('keydown', { cancelable: true }); Object.assign(event, { code: 'KeyV', repeat }); f.window.dispatchEvent(event) }
  keydown(false)
  f.sessionId.value = 'B'
  keydown(true)
  assert.equal(f.permissions.length, 1)
  const stream = f.grant(); await flush()
  assert.equal(stream.track.stopped, 1); assert.equal(f.voice.isRecording.value, false)
})
