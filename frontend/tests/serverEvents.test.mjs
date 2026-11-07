import { test } from 'node:test'
import assert from 'node:assert/strict'
import { serverEventsModule } from './serverEventsModule.mjs'

const { readServerEvents } = await import(serverEventsModule)
const encoder = new TextEncoder()
const body = text => new ReadableStream({
  start(controller) {
    for (const byte of encoder.encode(text)) controller.enqueue(Uint8Array.of(byte))
    controller.close()
  }
})
const collect = async (stream, options) => {
  const events = []
  for await (const event of readServerEvents(stream, options)) events.push(event)
  return events
}

for (const newline of ['\n', '\r\n', '\r']) {
  test(`SSE handles ${JSON.stringify(newline)} split across UTF-8 byte chunks`, async () => {
    const frame = ['event: chunk', 'data: {"content":"Привет 👋"}', '', ''].join(newline)
    assert.deepEqual(await collect(body(frame)), [{ event: 'chunk', data: { content: 'Привет 👋' } }])
  })
}

test('multi-line JSON and comment heartbeats share the same parser', async () => {
  let activities = 0
  const events = await collect(body(': heartbeat\n\nevent: state\ndata: {"count":\ndata: 2}\n\n'), {
    onActivity: () => activities++
  })
  assert.deepEqual(events, [{ event: 'state', data: { count: 2 } }])
  assert.ok(activities > 0)
})

test('EOF does not confirm a final event without its terminating blank line', async () => {
  assert.deepEqual(await collect(body('event: final\ndata: {}')), [])
})

test('invalid JSON and invalid wire payloads are visible errors', async () => {
  await assert.rejects(collect(body('data: {broken}\n\n')))
  await assert.rejects(collect(body('data: []\n\n')), /invalid event payload/)
})

test('abort cancels a pending read and releases the stream lock', async () => {
  let canceled = false
  const controller = new AbortController()
  const stream = new ReadableStream({ cancel() { canceled = true } })
  const pending = collect(stream, { signal: controller.signal })
  controller.abort()
  await assert.rejects(pending, { name: 'AbortError' })
  assert.equal(canceled, true)
  assert.equal(stream.locked, false)
})

test('obsolete session streams are canceled before publishing another event', async () => {
  assert.deepEqual(await collect(body('data: {}\n\n'), { isCurrent: () => false }), [])
})

test('a large buffered response yields to browser tasks before consuming every event', async () => {
  const frame = 'event: chunk\ndata: {"content":"x"}\n\n'
  const stream = new ReadableStream({ start(controller) {
    controller.enqueue(encoder.encode(frame.repeat(512)))
    controller.close()
  } })
  let responsive = false
  setTimeout(() => { responsive = true }, 0)
  let count = 0
  let yieldedBeforeEnd = false
  for await (const event of readServerEvents(stream)) {
    assert.equal(event.event, 'chunk')
    count++
    if (responsive && count < 512) yieldedBeforeEnd = true
  }
  assert.equal(count, 512)
  assert.ok(yieldedBeforeEnd, 'timers and input tasks must run during a buffered token burst')
})

test('session changes during a buffered response discard the remaining frames', async () => {
  const stream = new ReadableStream({ start(controller) {
    controller.enqueue(encoder.encode('data: {}\n\n'.repeat(3)))
    controller.close()
  } })
  let current = true
  const events = []
  for await (const event of readServerEvents(stream, { isCurrent: () => current })) {
    events.push(event)
    current = false
  }
  assert.equal(events.length, 1)
  assert.equal(stream.locked, false)
})
