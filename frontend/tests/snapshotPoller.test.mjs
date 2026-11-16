import { test } from 'node:test'
import { Buffer } from 'node:buffer'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'
const source = readFileSync(new URL('../src/services/snapshotPoller.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
const { createSnapshotPoller } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

test('slow history reads do not overlap and polling can resume', async () => {
  let release, calls = 0
  const poller = createSnapshotPoller(async () => { calls++; await new Promise(resolve => { release = resolve }) })
  const first = poller.tick()
  for (let i = 0; i < 30; i++) await poller.tick()
  assert.equal(calls, 1)
  release(); await first
  const second = poller.tick()
  assert.equal(calls, 2)
  release(); await second
})

for (const method of ['stop', 'interrupt']) {
  test(`${method} cancels only the history read`, async () => {
    let signal
    const poller = createSnapshotPoller(async input => {
      signal = input
      await new Promise(resolve => input.addEventListener('abort', resolve, { once: true }))
    })
    const request = poller.tick()
    assert.equal(signal.aborted, false)
    poller[method]()
    await request
    assert.equal(signal.aborted, true)
  })
}

test('history deadline cancels a stalled read', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] })
  let signal
  const poller = createSnapshotPoller(async input => {
    signal = input
    await new Promise(resolve => input.addEventListener('abort', resolve, { once: true }))
  })
  const request = poller.tick()
  t.mock.timers.tick(15_000)
  await request
  assert.equal(signal.aborted, true)
})
