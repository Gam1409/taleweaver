import { test } from 'node:test'
import assert from 'node:assert/strict'
import { effectScope, nextTick, ref } from 'vue'
import { controllerModule, entry, job, source, state } from './worldInfoModule.mjs'
const { useWorldInfo } = await import(controllerModule)
const tick = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)) }
function fixture(t) { const scope = effectScope(), sid = ref('session/a'); const c = scope.run(() => useWorldInfo(sid)); t.after(() => scope.stop()); return { c, sid, scope } }
const reply = value => Response.json(structuredClone(value))
function defaultReply(path) {
  if (path.includes('/entries/facets')) return reply({ groups: { items: [], total: 0 }, tags: { items: [], total: 0 }, kinds: { items: [], total: 0 } })
  if (path.endsWith('/entries/entry-1')) return reply(entry)
  if (path.includes('/entries?')) return reply({ entries: [entry], total: 1, next_offset: null })
  if (path.endsWith('/sources/source-1')) return reply({ source, revisions: [job] })
  return reply(state(decodeURIComponent(path.split('/')[2])))
}
test('session switch aborts old reads and never applies late source or entry results', async t => {
  const pending = []
  t.mock.method(globalThis, 'fetch', (path, options) => new Promise(resolve => pending.push({ path, signal: options.signal, resolve })))
  const { c, sid } = fixture(t)
  sid.value = 'session-b'
  assert.equal(pending[0].signal.aborted, true)
  pending[0].resolve(reply(state()))
  pending[1].resolve(reply(state('session-b')))
  await tick()
  assert.equal(c.data.state.session_id, 'session-b')
  const opening = c.openEntry('entry-1'); sid.value = 'session-c'
  assert.equal(pending[2].signal.aborted, true)
  pending[2].resolve(reply(entry)); pending[3].resolve(reply(state('session-c')))
  await opening; await tick()
  assert.equal(c.data.draft, null)
  assert.equal(c.data.state.session_id, 'session-c')
})
test('a late save response cannot restore an old-session draft or start new-session follow-up reads', async t => {
  let finish, saveSignal
  const calls = []
  t.mock.method(globalThis, 'fetch', (path, options) => {
    calls.push(path)
    if (options.method === 'PUT') return new Promise(resolve => { finish = resolve; saveSignal = options.signal })
    return defaultReply(path)
  })
  const { c, sid } = fixture(t); await tick(); await c.changeTab('review'); await c.openEntry(entry.id)
  c.data.draft.title = 'Local correction'
  const saving = c.saveEntry(); sid.value = 'session-b'; await tick()
  const before = calls.length
  assert.equal(saveSignal.aborted, true)
  finish(reply({ ...entry, title: 'Local correction', version: 3 }))
  await saving; await tick()
  assert.equal(c.data.draft, null); assert.equal(c.data.busy, '')
  assert.equal(calls.length, before)
})
test('conflicting saves retain edited facts and immutable original evidence', async t => {
  t.mock.method(globalThis, 'fetch', async (path, options) => options.method === 'PUT' ? Response.json({}, { status: 409 }) : defaultReply(path))
  const { c } = fixture(t); await tick(); await c.openEntry(entry.id)
  c.data.draft.facts[0].text = 'Corrected history'
  await c.saveEntry()
  assert.equal(c.dirty.value, true)
  assert.equal(c.data.draft.facts[0].text, 'Corrected history')
  assert.equal(c.data.draft.facts[0].original_text, entry.facts[0].text)
  assert.match(c.data.error, /draft is kept/); assert.equal(c.data.busy, '')
})
test('cancel failure remains retryable and resume reuses the original revision and cursor', async t => {
  let failures = 1
  const controls = []
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    if (path.endsWith('/cancel') || path.endsWith('/process')) {
      controls.push({ path, body: JSON.parse(options.body) })
      return failures-- > 0 ? Response.json({}, { status: 503 }) : reply({ source, revision: job })
    }
    return defaultReply(path)
  })
  const { c } = fixture(t); await tick()
  await c.control(job, 'cancel'); assert.equal(c.data.busy, ''); assert.ok(c.data.error)
  await c.control(job, 'cancel'); assert.equal(c.data.error, '')
  await c.control({ ...job, can_resume: true, cursor: 2 }, 'process')
  assert.equal(controls.length, 3)
  assert.ok(controls.every(value => value.path.includes(`/revisions/${job.id}/`)))
  assert.deepEqual(controls[2].body, { control_version: 3 })
})
test('upload starts analysis only when the saved revision explicitly permits a start', async t => {
  const calls = []
  let canStart = true
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    calls.push(path)
    if (path.endsWith('/sources') && options.method === 'POST') return reply({ source, revision: { ...job, can_start: canStart, can_resume: !canStart }, duplicate: !canStart })
    if (path.endsWith('/process')) return reply({ source, revision: job })
    return defaultReply(path)
  })
  const { c } = fixture(t); await tick()
  await c.upload(new File(['# coast'], 'coast.md'), '')
  assert.equal(calls.filter(path => path.endsWith('/process')).length, 1)
  canStart = false
  await c.upload(new File(['# coast'], 'coast.md'), '')
  assert.equal(calls.filter(path => path.endsWith('/process')).length, 1)
  assert.match(c.data.message, /existing processing progress/)
  assert.equal(c.data.job.id, job.id)
})
test('mixed-revision publication is rejected before mutation and paused index preserves success', async t => {
  const calls = []
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    calls.push(path)
    if (path.endsWith('/publish')) return reply({ published: 1, replaced: 0, source, index: state().index })
    return defaultReply(path, options)
  })
  const { c } = fixture(t); await tick(); await c.changeTab('review')
  c.data.entries.push({ ...entry, id: 'entry-2', source_revision_id: 'another-revision' })
  c.data.selected = [entry.id, 'entry-2']; await c.publish()
  assert.match(c.data.error, /one source version/); assert.equal(calls.some(path => path.endsWith('/publish')), false)
  c.data.selected = [entry.id]; await c.publish()
  assert.match(c.data.message, /accepted for this session/); assert.equal(c.data.state.index.paused, true)
})
test('closing the controller aborts requests without submitting cancellation', async t => {
  const calls = [], pending = []
  t.mock.method(globalThis, 'fetch', (path, options) => { calls.push(path); pending.push(options.signal); return new Promise(() => {}) })
  const { scope } = fixture(t); scope.stop()
  assert.equal(pending[0].aborted, true); assert.equal(calls.length, 1); assert.ok(!calls[0].endsWith('/cancel'))
})
test('a late upload response cannot dispatch analysis after switching sessions', async t => {
  let finish
  const calls = []
  t.mock.method(globalThis, 'fetch', (path, options) => {
    calls.push(path)
    if (path.endsWith('/sources') && options.method === 'POST') return new Promise(resolve => { finish = resolve })
    return defaultReply(path)
  })
  const { c, sid } = fixture(t); await tick()
  const upload = c.upload(new File(['# A coastal note'], 'coast.md'), '')
  await tick(); sid.value = 'session-b'; await tick()
  finish(reply({ source, revision: { ...job, can_start: true }, duplicate: false }))
  await upload; await tick()
  assert.equal(calls.some(path => path.endsWith('/process')), false)
  assert.equal(c.data.state.session_id, 'session-b')
  assert.equal(c.data.source, null)
})
test('publication confirmation keeps the displayed source CAS even if background status changes', async t => {
  let payload
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    if (path.endsWith('/publish')) { payload = JSON.parse(options.body); return Response.json({}, { status: 409 }) }
    return defaultReply(path)
  })
  const { c } = fixture(t); await tick(); await c.changeTab('review')
  c.data.selected = [entry.id]
  const selection = structuredClone({ source, entries: [entry] })
  c.data.state.sources[0].version = 99
  await c.publish(selection)
  assert.equal(payload.source_version, 5)
  assert.match(c.data.error, /draft is kept/)
  assert.deepEqual(c.data.selected, [entry.id])
})
test('source navigation aborts an old original-text preview and rejects its late response', async t => {
  let finish, signal
  const secondSource = { ...source, id: 'source-2', job: { ...job, id: 'revision-2', source_id: 'source-2' } }
  t.mock.method(globalThis, 'fetch', (path, options) => {
    if (path.includes('/content?')) return new Promise(resolve => { finish = resolve; signal = options.signal })
    if (path.endsWith('/sources/source-2')) return reply({ source: secondSource, revisions: [secondSource.job] })
    return defaultReply(path)
  })
  const { c } = fixture(t); await tick(); await c.openSource(source.id)
  const preview = c.previewSource(); await c.openSource(secondSource.id)
  assert.equal(signal.aborted, true)
  finish(reply({ id: job.id, content: 'The previous source text.' }))
  await preview
  assert.equal(c.data.source.source.id, secondSource.id)
  assert.equal(c.data.job.id, 'revision-2')
  assert.equal(c.data.content, null)
})
test('explicit source-version review includes archived records while default review remains draft-only', async t => {
  const queries = []
  t.mock.method(globalThis, 'fetch', (path, options) => { if (path.includes('/entries?')) queries.push(new URL(path, 'http://localhost').searchParams); return defaultReply(path, options) })
  const { c } = fixture(t); await tick(); await c.changeTab('review')
  assert.equal(queries.at(-1).get('view'), 'review')
  await c.reviewRevision({ ...job, id: 'saved-old-revision' })
  assert.equal(queries.at(-1).get('view'), 'all')
  assert.equal(queries.at(-1).get('source_revision_id'), 'saved-old-revision')
})
test('a large upload is retained without paid processing until an explicit start', async t => {
  const calls = []
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    calls.push(path)
    if (path.endsWith('/sources') && options.method === 'POST') return reply({ source, revision: { ...job, total_batches: 17, cursor: 0, can_start: true }, duplicate: false })
    return defaultReply(path)
  })
  const { c } = fixture(t); await tick(); await c.upload(new File(['# A retained book'], 'book.md'), '')
  assert.ok(calls.some(path => path.endsWith('/sources')))
  assert.equal(calls.some(path => path.endsWith('/process')), false)
  assert.match(c.data.message, /without starting analysis/)
})
test('original source pages replace the previous bounded excerpt without concatenation', async t => {
  const calls = []
  t.mock.method(globalThis, 'fetch', (path, options) => {
    if (path.includes('/content?')) { calls.push(path); const offset = Number(new URL(path, 'http://localhost').searchParams.get('offset')); return reply({ id: job.id, content: offset ? 'Second page' : 'First page', offset, next_offset: offset ? null : 8000, total_characters: 8009 }) }
    return defaultReply(path, options)
  })
  const { c } = fixture(t); await tick(); await c.openSource(source.id)
  await c.previewSource(); await c.previewSource(8000)
  assert.equal(c.data.content.content, 'Second page')
  assert.equal(c.data.content.offset, 8000)
  assert.ok(calls.every(path => path.includes('limit=8000')))
})
test('saving a detail on page two preserves catalog page, filters and sort', async t => {
  const offsets = []
  t.mock.method(globalThis, 'fetch', (path, options) => {
    if (path.includes('/entries?')) { const offset = Number(new URL(path, 'http://localhost').searchParams.get('offset')); offsets.push(offset); return reply({ entries: [entry], total: 120, next_offset: offset + 50 < 120 ? offset + 50 : null }) }
    if (options.method === 'PUT') return reply({ ...entry, title: 'Corrected lighthouse', version: 3 })
    return defaultReply(path)
  })
  const { c } = fixture(t); await tick(); await c.changeTab('review')
  c.data.groupFilter = 'Coast'; c.data.sort = 'title_asc'
  await c.catalog.search(); await c.catalog.loadEntries(50); await c.openEntry(entry.id)
  c.data.draft.title = 'Corrected lighthouse'; await c.saveEntry()
  assert.equal(c.data.offset, 50); assert.equal(offsets.at(-1), 50)
  assert.equal(c.data.groupFilter, 'Coast'); assert.equal(c.data.sort, 'title_asc')
})
test('deleting the final item on the last page clamps to the remaining last page', async t => {
  let total = 101
  const offsets = []
  t.mock.method(globalThis, 'fetch', (path, options) => {
    if (path.includes('/entries?')) { const offset = Number(new URL(path, 'http://localhost').searchParams.get('offset')); offsets.push(offset); return reply({ entries: offset < total ? [entry] : [], total, next_offset: offset + 50 < total ? offset + 50 : null }) }
    if (options.method === 'DELETE') { total = 100; return reply({ deleted: true, index: state().index }) }
    return defaultReply(path)
  })
  const { c } = fixture(t); await tick(); await c.changeTab('review'); await c.catalog.loadEntries(100); await c.openEntry(entry.id)
  await c.removeEntry()
  assert.equal(c.data.offset, 50)
  assert.deepEqual(offsets.slice(-2), [100, 50])
})
test('returning from a loading detail aborts the read and cannot reopen a late result', async t => {
  let finish, signal
  t.mock.method(globalThis, 'fetch', (path, options) => {
    if (path.endsWith('/entries/entry-1')) return new Promise(resolve => { finish = resolve; signal = options.signal })
    return defaultReply(path)
  })
  const { c } = fixture(t); await tick()
  const opening = c.openEntry(entry.id)
  assert.equal(c.data.entryLoading, true)
  c.closeEntry(); assert.equal(signal.aborted, true)
  finish(reply(entry)); await opening
  assert.equal(c.data.draft, null); assert.equal(c.data.entryLoading, false)
})
test('background processing completion preserves the catalog page while an entry is open', async t => {
  let reads = 0, finishPoll
  const offsets = []
  t.mock.method(globalThis, 'fetch', (path, options) => {
    if (path.endsWith('/world-info')) {
      if (++reads === 1) { const working = state(); working.sources[0].job.status = 'processing'; return reply(working) }
      return new Promise(resolve => { finishPoll = resolve })
    }
    if (path.includes('/entries?')) { const offset = Number(new URL(path, 'http://localhost').searchParams.get('offset')); offsets.push(offset); return reply({ entries: [entry], total: 120, next_offset: offset + 50 < 120 ? offset + 50 : null }) }
    return defaultReply(path, options)
  })
  const { c } = fixture(t); await tick(); await c.changeTab('review'); await c.catalog.loadEntries(50); await c.openEntry(entry.id)
  assert.equal(typeof finishPoll, 'function')
  finishPoll(reply(state())); await tick()
  assert.equal(c.data.offset, 50); assert.equal(offsets.at(-1), 50)
  assert.equal(c.data.draft.id, entry.id)
})
test('saving remains busy through catalog and overview refresh before editing is enabled again', async t => {
  let refreshing = false, finishEntries, finishState
  t.mock.method(globalThis, 'fetch', (path, options) => {
    if (options.method === 'PUT') { refreshing = true; return reply({ ...entry, title: 'Saved correction', version: 3 }) }
    if (refreshing && path.includes('/entries?')) return new Promise(resolve => { finishEntries = resolve })
    if (refreshing && path.endsWith('/world-info')) return new Promise(resolve => { finishState = resolve })
    return defaultReply(path)
  })
  const { c } = fixture(t); await tick(); await c.changeTab('review'); await c.openEntry(entry.id)
  c.data.draft.title = 'Saved correction'
  const saving = c.saveEntry(); await tick()
  const duringEntries = c.data.busy
  const duplicate = await c.saveEntry(), afterDuplicate = c.data.busy
  finishEntries(reply({ entries: [entry], total: 1, next_offset: null })); await tick()
  const duringState = c.data.busy
  finishState(reply(state())); await saving
  assert.equal(duringEntries, 'Saving entry…'); assert.equal(duringState, 'Saving entry…')
  assert.equal(duplicate, false); assert.equal(afterDuplicate, 'Saving entry…')
  assert.equal(c.data.busy, ''); assert.equal(c.dirty.value, false)
})
for (const operation of ['save', 'publish', 'unpublish', 'remove']) {
  test(`${operation} refreshes group and tag counts without resetting the catalog scope`, async t => {
    let changed = false
    const filters = []
    const updated = { ...entry, group_name: 'New archive group', tags: ['new-tag'], version: 3 }
    const facet = (name, count) => ({ items: count ? [{ name, count }] : [], total: count })
    t.mock.method(globalThis, 'fetch', async (path, options) => {
      if (options.method !== 'GET') {
        changed = true
        if (operation === 'save') return reply(updated)
        if (operation === 'publish') return reply({ published: 1, replaced: 0, source, index: state().index })
        return reply({ deleted: true, index: state().index })
      }
      if (path.includes('/entries/facets')) {
        filters.push(new URL(path, 'http://localhost').searchParams)
        const gone = changed && operation !== 'save'
        return reply({ groups: facet(changed ? updated.group_name : 'Old group', gone ? 0 : 1), tags: facet(changed ? 'new-tag' : 'old-tag', gone ? 0 : 1), kinds: facet('background_lore', gone ? 0 : 1) })
      }
      return defaultReply(path)
    })
    const { c } = fixture(t); await tick(); await c.changeTab('review')
    c.data.query = 'archive'; c.data.sort = 'title_asc'; c.data.facetQuery = 'ar'
    await c.catalog.search(); await c.openEntry(entry.id)
    if (operation === 'save') { c.data.draft.group_name = updated.group_name; c.data.draft.tags = updated.tags; await c.saveEntry() }
    if (operation === 'publish') { c.data.selected = [entry.id]; await c.publish() }
    if (operation === 'unpublish') await c.unpublish()
    if (operation === 'remove') await c.removeEntry()
    assert.equal(changed, true)
    assert.deepEqual(c.data.facets.groups.items, operation === 'save' ? [{ name: updated.group_name, count: 1 }] : [])
    assert.deepEqual(c.data.facets.tags.items, operation === 'save' ? [{ name: 'new-tag', count: 1 }] : [])
    assert.equal(filters.at(-1).get('query'), 'archive')
    assert.equal(filters.at(-1).get('facet_query'), 'ar')
    assert.equal(c.data.sort, 'title_asc')
  })
}
test('processing refresh retains authoritative server budgets and controls without predicting a resume', async t => {
  let started = false
  const exhausted = { ...job, attempts: 8, request_limit: 8, cursor: 1, total_batches: 2, status: 'failed', last_error_code: 'invalid_output', can_start: false, can_resume: false, can_cancel: false }
  const methods = []
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    if (path.endsWith('/process')) { started = true; methods.push(JSON.parse(options.body)); return reply({ source: { ...source, job: exhausted }, revision: exhausted }) }
    if (started && path.endsWith('/world-info')) { const latest = state(); latest.sources[0].job = exhausted; return reply(latest) }
    if (started && path.endsWith('/sources/source-1')) return reply({ source: { ...source, job: exhausted }, revisions: [exhausted] })
    return defaultReply(path)
  })
  const { c } = fixture(t); await tick(); await c.openSource(source.id)
  await c.control({ ...job, request_limit: null, total_batches: 0, cursor: 0, can_start: true }, 'process')
  assert.deepEqual(methods, [{ control_version: job.control_version }])
  assert.equal(c.data.job.attempts, 8); assert.equal(c.data.job.request_limit, 8)
  assert.equal(c.data.job.can_resume, false); assert.equal(c.data.job.last_error_code, 'invalid_output')
})
