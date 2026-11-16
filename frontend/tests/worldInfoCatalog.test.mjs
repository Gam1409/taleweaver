import { test } from 'node:test'
import assert from 'node:assert/strict'
import { effectScope, reactive } from 'vue'
import { catalogModule, entry, state } from './worldInfoModule.mjs'
const { useWorldInfoCatalog, worldInfoCatalogState } = await import(catalogModule)
function fixture(t) {
  const data = reactive({ ...worldInfoCatalogState(), state: state(), tab: 'review', query: '', revisionFilter: '', entries: [], total: 0, next: null, selected: [], draft: null, baseline: '', error: '', message: '', busy: '' })
  const calls = [], rows = Array.from({ length: 10000 }, (_, i) => ({ ...entry, id: `entry-${i}`, group_name: i % 2 ? 'Coast' : 'Archives' }))
  const api = {
    entries: async (view, _query, _revision, offset, filters) => { calls.push({ name: 'entries', view, offset, filters }); return { entries: rows.slice(offset, offset + 50), total: rows.length, next_offset: offset + 50 < rows.length ? offset + 50 : null } },
    facets: async filters => { calls.push({ name: 'facets', filters }); return { groups: { items: [{ name: 'Coast', count: 5000 }], total: 2 }, tags: { items: [], total: 0 }, kinds: { items: [], total: 0 } } },
    previewBulk: async intent => { calls.push({ name: 'preview', intent }); return { action: intent.action, count: 10000, facts_count: 20000, active_count: 0, sample: rows.slice(0, 5), selection_hash: 'fixed-selection', source_version: null, source_revision_id: null } },
    applyBulk: async intent => { calls.push({ name: 'apply', intent }); return { action: intent.action, matched: 10000, changed: 10000, index: state().index } },
  }
  const request = async (_key, action) => action(api, new AbortController().signal)
  let succeed = true
  const mutate = async (_label, action) => { await action(api, new AbortController().signal); return succeed }
  const scope = effectScope(), c = scope.run(() => useWorldInfoCatalog(data, request, mutate, async () => {}))
  t.after(() => scope.stop())
  return { c, data, calls, api, failApply() { succeed = false } }
}
test('10,000-entry pagination replaces one bounded page and clears page-only selection', async t => {
  const { c, data } = fixture(t)
  await c.loadEntries(); data.selected = ['entry-0']
  await c.loadEntries(50)
  assert.equal(data.entries.length, 50); assert.equal(data.entries[0].id, 'entry-50')
  assert.equal(data.offset, 50); assert.equal(data.next, 100); assert.equal(data.total, 10000)
  assert.deepEqual(data.selected, [])
  await c.loadEntries(0); assert.equal(data.entries.length, 50); assert.equal(data.entries[0].id, 'entry-0')
})
test('search/facets retain exact group/tag/kind/source/sort scope and allow all saved records', async t => {
  const { c, data, calls } = fixture(t)
  Object.assign(data, { catalogView: 'all', query: 'coast winter', groupFilter: '', tagFilter: 'history', kindFilter: 'rumor', revisionFilter: 'r/1', sort: 'title_desc' })
  await c.search()
  const filters = calls.find(call => call.name === 'entries').filters
  assert.deepEqual(filters, { view: 'all', query: 'coast winter', source_revision_id: 'r/1', group_name: '', tag: 'history', kind: 'rumor', sort: 'title_desc' })
  assert.deepEqual(calls.find(call => call.name === 'facets').filters, filters)
  data.groupFilter = null; assert.equal(c.filters().group_name, null)
  data.tab = 'active'; assert.equal(c.filters().view, 'active')
})
test('bulk preview covers the full query and keeps an immutable confirmed scope across pages', async t => {
  const { c, data, calls } = fixture(t)
  await c.previewBulk('set_group', 'Coastal history')
  assert.equal(data.bulkPreview.count, 10000); assert.equal(data.bulkPreview.sample.length, 5)
  const selection = c.bulkSelection()
  data.query = 'a new search'
  assert.equal(data.bulkPreview, null)
  await c.applyBulk(selection)
  const applied = calls.find(call => call.name === 'apply').intent
  assert.equal(applied.filters.query, ''); assert.equal(applied.group_name, 'Coastal history')
  assert.equal(applied.selection_hash, 'fixed-selection')
  assert.match(data.message, /Confirmed changes saved/)
})
test('bulk publication requires one explicit immutable source version and dirty edits remain local', async t => {
  const { c, data, calls } = fixture(t)
  await c.previewBulk('publish'); assert.match(data.error, /single source version/)
  assert.equal(calls.length, 0)
  data.revisionFilter = 'revision-1'
  data.draft = { ...entry, title: 'Local changes' }; data.baseline = JSON.stringify(entry)
  await c.previewBulk('add_tags', '', ['history'])
  assert.match(data.error, /Save or discard/); assert.equal(calls.length, 0)
})
test('failed apply invalidates the confirmation without dropping filters or the entry draft', async t => {
  const { c, data, failApply } = fixture(t)
  data.groupFilter = 'Coast'; await c.previewBulk('add_tags', '', ['history'])
  const selection = c.bulkSelection(); failApply()
  data.draft = structuredClone(entry); data.baseline = JSON.stringify(entry)
  await c.applyBulk(selection)
  assert.equal(data.bulkPreview, null); assert.equal(data.groupFilter, 'Coast')
  assert.equal(data.draft.id, entry.id)
})
test('resetting session scope fences an outstanding bulk apply result', async t => {
  const { c, data, api } = fixture(t)
  await c.previewBulk('set_group', 'Coast'); const selection = c.bulkSelection()
  let finish
  api.applyBulk = () => new Promise(resolve => { finish = resolve })
  const applying = c.applyBulk(selection); c.reset(); data.message = 'New session'
  finish({ changed: 10000 }); await applying
  assert.equal(data.message, 'New session'); assert.equal(data.entries.length, 0)
})
test('editing bulk parameters invalidates an outstanding preview before it can be confirmed', async t => {
  const { c, data, api } = fixture(t)
  let finish
  api.previewBulk = () => new Promise(resolve => { finish = resolve })
  const preview = c.previewBulk('set_group', 'Original group')
  c.clearBulk()
  finish({ action: 'set_group', count: 10000, sample: [], selection_hash: 'old' })
  await preview
  assert.equal(data.bulkPreview, null); assert.equal(c.bulkSelection(), null)
})
test('unsubmitted search changes cannot bulk-edit a different scope or jump into its second page', async t => {
  const { c, data, calls } = fixture(t)
  await c.loadEntries()
  data.query = 'a new query'
  assert.equal(c.hasPendingFilters(), true)
  await c.previewBulk('set_group', 'Coast')
  assert.match(data.error, /Apply the current search/)
  assert.equal(calls.some(call => call.name === 'preview'), false)
  await c.loadEntries(50)
  assert.equal(data.offset, 0); assert.equal(c.hasPendingFilters(), false)
})
