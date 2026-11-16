import { test } from 'node:test'
import assert from 'node:assert/strict'
import { serviceModule, displayModule, source, job, entry, limits } from './worldInfoModule.mjs'
const { worldInfoService, worldInfoEntryPayload } = await import(serviceModule)
const { validateWorldInfoFile, infoCount, indexMessage, worldInfoSourceOptions, worldInfoTagLabel } = await import(displayModule)

test('World Info serialization targets only the captured session and retains CAS versions', async t => {
  const calls = []
  t.mock.method(globalThis, 'fetch', async (path, options) => { calls.push({ path, ...options }); return Response.json({}) })
  const controller = new AbortController(), api = worldInfoService('session/a', controller.signal)
  await api.state(); await api.process(job); await api.cancel(job); await api.save(entry)
  await api.publish(source, job.id, [entry]); await api.removeEntry(entry); await api.removeSource(source); await api.rebuild()
  assert.ok(calls.every(call => call.path.startsWith('/adventures/session%2Fa/world-info')))
  assert.ok(calls.every(call => call.signal === controller.signal))
  assert.ok(calls.every(call => !call.path.includes('/templates/')))
  assert.deepEqual(JSON.parse(calls[1].body), { control_version: 3 })
  assert.deepEqual(JSON.parse(calls[2].body), { control_version: 3 })
  assert.deepEqual(JSON.parse(calls[4].body), { revision_id: job.id, source_version: 5, entries: [{ id: entry.id, version: 2 }] })
  assert.match(calls[5].path, /\?version=2$/)
  assert.match(calls[6].path, /\?version=5$/)
  assert.equal(calls[7].method, 'POST')
})
test('entry writes include editable facts only, keeping original evidence server-owned', () => {
  const payload = worldInfoEntryPayload({ ...entry, known_by: ['MIRA'], facts: [{ ...entry.facts[0], text: 'An author correction.' }] })
  assert.deepEqual(payload.known_by, [])
  assert.deepEqual(payload.facts, [{ id: 'fact-1', text: 'An author correction.' }])
  assert.equal('original_text' in payload.facts[0], false)
  assert.deepEqual(worldInfoEntryPayload({ ...entry, audience: 'restricted', known_by: ['MIRA'] }).known_by, ['MIRA'])
  assert.deepEqual(worldInfoEntryPayload({ ...entry, audience: 'restricted', known_by: ['DORMANT'], unresolved_known_by: ['DORMANT'] }).resolve_known_by, [])
  assert.deepEqual(worldInfoEntryPayload({ ...entry, audience: 'restricted', known_by: ['DORMANT'], unresolved_known_by: ['DORMANT'] }).known_by, ['DORMANT'])
  assert.deepEqual(worldInfoEntryPayload({ ...entry, audience: 'restricted', known_by: ['MIRA'], unresolved_known_by: ['MIRA'], resolve_known_by: ['MIRA'] }).resolve_known_by, ['MIRA'])
  assert.equal('group_name' in worldInfoEntryPayload(entry), false)
  assert.equal(worldInfoEntryPayload({ ...entry, group_name: '' }).group_name, '')
  assert.equal(worldInfoEntryPayload({ ...entry, group_name: 'Archives' }).group_name, 'Archives')
})
test('tag labels and entry writes preserve exact saved hashtag and delimiter identities', () => {
  const tags = ['#harbour', 'harbour', 'harbour history', 'trade,craft', 'line\r\nbreak\tlabel']
  assert.deepEqual(tags.map(worldInfoTagLabel), ['#harbour', '#harbour', '#harbour history', '#trade,craft', '#line\r\nbreak\tlabel'])
  assert.deepEqual(worldInfoEntryPayload({ ...entry, tags }).tags, tags)
})
test('multipart uploads and replacement versions do not set JSON content type', async t => {
  const calls = []
  t.mock.method(globalThis, 'fetch', async (path, options) => { calls.push({ path, ...options }); return Response.json({}) })
  const api = worldInfoService('sid', new AbortController().signal), file = new File(['# Coast'], 'coast.md')
  await api.upload(file, ' Coast '); await api.upload(file, ' A previously entered title ', source)
  assert.equal(calls[0].includeJson, false)
  assert.equal(calls[0].body.get('title'), 'Coast')
  assert.equal(calls[1].body.get('expected_version'), '5')
  assert.equal(calls[1].body.has('title'), false)
  assert.deepEqual([...calls[1].body.keys()], ['file', 'expected_version'])
  assert.match(calls[1].path, /sources\/source-1\/revisions$/)
})
test('search pagination and revision filtering use encoded query parameters', async t => {
  let url
  t.mock.method(globalThis, 'fetch', async path => { url = path; return Response.json({}) })
  await worldInfoService('sid', new AbortController().signal).entries('all', 'harbour & coast', 'r/2', 50)
  const query = new URL(url, 'http://localhost').searchParams
  assert.equal(query.get('view'), 'all'); assert.equal(query.get('query'), 'harbour & coast')
  assert.equal(query.get('source_revision_id'), 'r/2'); assert.equal(query.get('offset'), '50')
})
test('API failure text never exposes uploaded data or upstream error details', async t => {
  t.mock.method(globalThis, 'fetch', async () => Response.json({ detail: 'PRIVATE_SOURCE upstream credentials' }, { status: 409 }))
  await assert.rejects(worldInfoService('sid', new AbortController().signal).state(), error => error.status === 409 && /draft is kept/.test(error.message) && !/PRIVATE|credentials/.test(error.message))
})
test('file validation agrees on exact UTF-8 byte and Unicode codepoint boundaries', async () => {
  const file = new File(['🌊海'], 'coast.MD')
  await validateWorldInfoFile(file, { ...limits, max_source_bytes: 7, max_source_characters: 2 })
  await assert.rejects(validateWorldInfoFile(file, { ...limits, max_source_bytes: 6 }), /bytes/)
  await assert.rejects(validateWorldInfoFile(file, { ...limits, max_source_characters: 1 }), /characters/)
  await assert.rejects(validateWorldInfoFile(new File([new Uint8Array([255])], 'bad.md'), limits))
  await assert.rejects(validateWorldInfoFile(new File(['{'], 'bad.json'), limits), /JSON/)
  await assert.rejects(validateWorldInfoFile(new File([' '], 'empty.md'), limits), /empty/)
  await assert.rejects(validateWorldInfoFile(new File(['ok'], 'other.txt'), limits), /Markdown/)
})
test('metrics keep unknown distinct from zero and explain index state separately from saving', () => {
  assert.equal(infoCount(null), '—'); assert.equal(infoCount(0), '0')
  assert.match(indexMessage({ enabled: false }), /disabled.*stay saved/)
  assert.match(indexMessage({ enabled: true, paused: true }), /saved.*paused.*lexical/)
  assert.match(indexMessage({ enabled: true, paused: false, status: 'error' }), /saved.*another attempt/)
  assert.match(indexMessage({ enabled: true, paused: false, desired_revision: 4, indexed_revision: 3 }), /saved.*queued/)
})
test('Active source options use the accepted revision ID while a newer draft is current', () => {
  const current = { ...source, current_revision: 2, published_revision: 1, published_revision_id: 'accepted-revision-1', job: { ...job, id: 'new-draft-2', number: 2 } }
  const active = worldInfoSourceOptions([current], null, true), review = worldInfoSourceOptions([current], null, false)
  assert.equal(active[0].id, 'accepted-revision-1'); assert.match(active[0].title, /version 1.*Accepted/)
  assert.equal(review[0].id, 'new-draft-2'); assert.match(review[0].title, /version 2/)
})
