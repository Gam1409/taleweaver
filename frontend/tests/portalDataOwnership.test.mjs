import { test } from 'node:test'
import assert from 'node:assert/strict'
import { portalDataFixture, deferred } from './portalDataModule.mjs'

test('a late note response updates only its submitted session and keeps the new editor', async t => {
  const response = deferred(), writes = []
  const f = await portalDataFixture(t, { updateSession: (id, payload) => {
    writes.push({ id, payload })
    return response.promise
  } })
  f.data.openEditNote('A', 'Original A')
  const save = f.data.saveSessionNote('Saved A')
  f.data.editNoteSessionId.value = null
  f.data.openEditNote('B', 'Unsaved B draft')
  response.resolve({ game_id: 'A', status_note: 'Saved A' })
  await save
  assert.deepEqual(writes, [{ id: 'A', payload: { status_note: 'Saved A' } }])
  assert.deepEqual(f.data.sessions.value.map(row => row.status_note), ['Saved A', 'Original B'])
  assert.equal(f.data.editNoteSessionId.value, 'B')
  assert.equal(f.data.editNoteValue.value, 'Unsaved B draft')
  assert.equal(f.data.isSavingNote.value, false)
})

test('reopening the same session gives the new note editor its own lifetime', async t => {
  const response = deferred()
  const f = await portalDataFixture(t, { updateSession: () => response.promise })
  f.data.openEditNote('A', 'Original A')
  const save = f.data.saveSessionNote('Saved A')
  f.data.editNoteSessionId.value = null
  f.data.openEditNote('A', 'New draft for A')
  response.resolve({ game_id: 'A', status_note: 'Saved A' })
  await save
  assert.equal(f.data.sessions.value[0].status_note, 'Saved A')
  assert.equal(f.data.editNoteSessionId.value, 'A')
  assert.equal(f.data.editNoteValue.value, 'New draft for A')
})

test('a pending save prevents duplicate or overlapping PATCH requests', async t => {
  const response = deferred(), calls = []
  const f = await portalDataFixture(t, { updateSession: (id, payload) => {
    calls.push({ id, payload }); return response.promise
  } })
  f.data.openEditNote('A', 'Original A')
  const first = f.data.saveSessionNote('First')
  void f.data.saveSessionNote('Duplicate')
  f.data.openEditNote('B', 'B draft')
  void f.data.saveSessionNote('Overlapping')
  assert.equal(calls.length, 1)
  assert.equal(f.data.isSavingNote.value, true)
  response.resolve({ game_id: 'A', status_note: 'First' })
  await first
  assert.equal(f.data.editNoteSessionId.value, 'B')
  assert.equal(f.data.isSavingNote.value, false)
})

test('normal note save closes its editor and subsequent saves remain possible', async t => {
  const f = await portalDataFixture(t)
  await f.data.saveSessionNote('No editor')
  assert.equal(f.calls.length, 0)
  f.data.openEditNote('A', 'Original A')
  await f.data.saveSessionNote('Saved A')
  assert.equal(f.data.editNoteSessionId.value, null)
  assert.equal(f.data.editNoteValue.value, '')
  f.data.openEditNote('B', 'Original B')
  await f.data.saveSessionNote('Saved B')
  assert.deepEqual(f.calls.map(call => call.id), ['A', 'B'])
  assert.deepEqual(f.data.sessions.value.map(row => row.status_note), ['Saved A', 'Saved B'])
})

test('a failed save retains the persisted note and replacement editor', async t => {
  const response = deferred()
  const f = await portalDataFixture(t, { updateSession: () => response.promise })
  f.data.openEditNote('A', 'Original A')
  const save = f.data.saveSessionNote('Attempt A')
  f.data.openEditNote('B', 'B draft')
  response.reject(new Error('Synthetic network failure'))
  await save
  assert.deepEqual(f.data.sessions.value.map(row => row.status_note), ['Original A', 'Original B'])
  assert.equal(f.data.editNoteSessionId.value, 'B')
  assert.equal(f.data.editNoteValue.value, 'B draft')
  assert.equal(f.data.errorMsg.value, 'Synthetic network failure')
  assert.equal(f.data.isSavingNote.value, false)
})

test('the completed request releases saving state before a new editor starts its own save', async t => {
  const first = deferred(), second = deferred(), calls = []
  const f = await portalDataFixture(t, { updateSession: (id, payload) => {
    calls.push({ id, payload })
    return calls.length === 1 ? first.promise : second.promise
  } })
  f.data.openEditNote('A', 'Original A')
  const saveA = f.data.saveSessionNote('Saved A')
  f.data.openEditNote('B', 'B draft')
  assert.equal(f.data.isSavingNote.value, true)
  first.resolve({ game_id: 'A', status_note: 'Saved A' })
  await saveA
  const saveB = f.data.saveSessionNote('Saved B')
  assert.equal(f.data.isSavingNote.value, true)
  assert.deepEqual(calls.map(call => call.id), ['A', 'B'])
  second.resolve({ game_id: 'B', status_note: 'Saved B' })
  await saveB
  assert.equal(f.data.isSavingNote.value, false)
  assert.equal(f.data.editNoteSessionId.value, null)
  assert.deepEqual(f.data.sessions.value.map(row => row.status_note), ['Saved A', 'Saved B'])
})

test('a late success cannot reopen a canceled note editor', async t => {
  const response = deferred()
  const f = await portalDataFixture(t, { updateSession: () => response.promise })
  f.data.openEditNote('A', 'Original A')
  const save = f.data.saveSessionNote('Saved A')
  f.data.editNoteSessionId.value = null
  response.resolve({ game_id: 'A', status_note: 'Saved A' })
  await save
  assert.equal(f.data.editNoteSessionId.value, null)
  assert.equal(f.data.sessions.value[0].status_note, 'Saved A')
  assert.equal(f.data.isSavingNote.value, false)
})

test('hydration preserves canonical tone IDs and metadata for both portal lists', async t => {
  const f = await portalDataFixture(t)
  assert.deepEqual(f.data.templates.value[0].selected_tone, f.tone)
  assert.deepEqual(f.data.sessions.value[0].selected_tone, f.tone)
  const options = f.filters.extractAvailableTones(f.data.templates.value, f.data.sessions.value,
    f.data.toneCatalog.value)
  assert.deepEqual(options, [{ id: 'heroic-epic', name: 'Heroic & Epic' }])
  for (const [section, rows] of [['templates', f.data.templates], ['sessions', f.data.sessions]]) {
    const filters = f.scope.run(() => f.filters.usePortalFilters(rows, section))
    filters.selectedTone.value = 'heroic-epic'
    assert.equal(filters.filteredCount.value, rows.value.length)
    filters.searchQuery.value = 'unmatched'
    assert.equal(filters.filteredCount.value, 0)
    filters.searchQuery.value = 'archive'
    assert.equal(filters.filteredCount.value, rows.value.length)
  }
  assert.equal(f.filters.formatCatalogLabel(f.data.templates.value[0].selected_tone), 'Heroic & Epic')
})

test('refresh keeps legacy tone shapes and custom IDs available without rewriting them', async t => {
  const tones = [
    JSON.stringify({ id: 'heroic-epic', name: 'Heroic & Epic' }),
    'heroic-epic', { id: 'custom-tone', name: 'Custom tone' }, null, '{unparsed'
  ]
  const rows = tones.map((selected_tone, index) => ({
    template_id: `template-${index}`, title: 'Archive', is_ready: true, selected_tone
  }))
  const f = await portalDataFixture(t, { listAdventureTemplates: async () => structuredClone(rows) })
  assert.deepEqual(f.data.templates.value.map(row => row.selected_tone), tones)
  assert.deepEqual(f.data.templates.value.map(row => f.filters.extractToneId(row.selected_tone)),
    ['heroic-epic', 'heroic-epic', 'custom-tone', '', '{unparsed'])
  const options = f.filters.extractAvailableTones(f.data.templates.value, [], f.data.toneCatalog.value)
  assert.equal(options.filter(row => row.id === 'heroic-epic').length, 1)
  assert.ok(options.some(row => row.id === 'custom-tone'))
  await f.data.fetchPortalData()
  assert.deepEqual(f.data.templates.value.map(row => row.selected_tone), tones)
})

test('canonical tone filtering still combines with rule type and art style', async t => {
  const tone = { id: 'heroic-epic', name: 'Heroic & Epic' }
  const rows = [
    { template_id: 'match', rule_enforcement_mode: 'story', selected_image_styles: [{ id: 'ink-sketch', name: 'Ink Sketch' }] },
    { template_id: 'other-style', rule_enforcement_mode: 'story', selected_image_styles: [{ id: 'paint', name: 'Paint' }] },
    { template_id: 'other-type', rule_enforcement_mode: 'rpg', selected_image_styles: [{ id: 'ink-sketch', name: 'Ink Sketch' }] }
  ].map(row => ({ ...row, title: 'Archive', is_ready: true, selected_tone: tone }))
  const f = await portalDataFixture(t, { listAdventureTemplates: async () => structuredClone(rows) })
  const filters = f.scope.run(() => f.filters.usePortalFilters(f.data.templates, 'templates'))
  filters.selectedTone.value = 'heroic-epic'
  filters.selectedType.value = 'story'
  filters.selectedStyle.value = 'ink-sketch'
  assert.deepEqual(filters.filteredItems.value.map(row => row.template_id), ['match'])
  assert.deepEqual(f.data.templates.value[0].selected_image_styles, rows[0].selected_image_styles)
})
