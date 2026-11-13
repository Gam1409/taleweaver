import { watch } from 'vue'
import type { WorldInfoApi, WorldInfoRequest } from '@/services/worldInfoService'
import type { WorldInfoBulkPreview, WorldInfoBulkRequest, WorldInfoEntry, WorldInfoEntrySummary, WorldInfoFacets, WorldInfoFilters, WorldInfoState, WorldInfoTab } from '@/types/worldInfo'

export function worldInfoCatalogState() {
  return { offset: 0, appliedFilters: '', catalogView: 'review' as 'review' | 'all', groupFilter: null as string | null, tagFilter: '', kindFilter: '' as '' | NonNullable<WorldInfoFilters['kind']>, sort: 'newest' as WorldInfoFilters['sort'], facets: null as WorldInfoFacets | null, facetQuery: '', catalogLoading: false, bulkPreview: null as WorldInfoBulkPreview | null, bulkIntent: null as WorldInfoBulkRequest | null }
}
type Host = ReturnType<typeof worldInfoCatalogState> & {
  state: WorldInfoState | null; tab: WorldInfoTab; query: string; revisionFilter: string
  entries: WorldInfoEntrySummary[]; total: number; next: number | null; selected: string[]
  draft: WorldInfoEntry | null; baseline: string; error: string; message: string; busy: string
}
type Mutate = (label: string, action: (api: WorldInfoApi, signal: AbortSignal) => Promise<unknown>) => Promise<boolean>
export interface WorldInfoBulkSelection { intent: WorldInfoBulkRequest; preview: WorldInfoBulkPreview }

export function useWorldInfoCatalog(data: Host, request: WorldInfoRequest, mutate: Mutate, refresh: () => Promise<void>) {
  let revision = 0
  let scopeRevision = 0
  let bulkRevision = 0
  const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value))
  function filters(): WorldInfoFilters {
    return { view: data.tab === 'active' ? 'active' : data.revisionFilter || data.catalogView === 'all' ? 'all' : 'review', query: data.query, source_revision_id: data.revisionFilter || undefined, group_name: data.groupFilter, tag: data.tagFilter || undefined, kind: data.kindFilter || undefined, sort: data.sort }
  }
  function clearBulk() { bulkRevision++; data.bulkPreview = null; data.bulkIntent = null }
  watch(() => JSON.stringify(filters()), clearBulk, { flush: 'sync' })
  const hasPendingFilters = () => !!data.appliedFilters && JSON.stringify(filters()) !== data.appliedFilters
  async function loadEntries(offset = 0) {
    const token = ++revision
    const selection = filters()
    if (offset && hasPendingFilters()) offset = 0
    data.catalogLoading = true
    const result = await request('entries', api => api.entries(selection.view, '', '', offset, selection))
    if (token !== revision) return
    data.catalogLoading = false
    if (!result) return
    if (offset && result.total <= offset) { await loadEntries(Math.max(0, Math.floor((result.total - 1) / 50) * 50)); return }
    data.entries = result.entries
    data.total = result.total
    data.next = result.next_offset
    data.offset = offset
    data.appliedFilters = JSON.stringify(selection)
    data.selected = []
  }
  async function loadFacets() {
    const selection = filters(), query = data.facetQuery
    const signature = JSON.stringify({ selection, query })
    const result = await request('facets', api => api.facets(selection, query))
    if (result && signature === JSON.stringify({ selection: filters(), query: data.facetQuery })) data.facets = result
  }
  async function search() { await Promise.all([loadEntries(), loadFacets()]) }
  async function selectGroup(value: string | null) { data.groupFilter = value; await search() }
  async function previewBulk(action: WorldInfoBulkRequest['action'], group = '', tags: string[] = []) {
    if (data.busy) return
    if (hasPendingFilters()) { data.error = 'Apply the current search and filters before previewing bulk changes.'; return }
    if (data.draft && JSON.stringify(data.draft) !== data.baseline) { data.error = 'Save or discard the entry draft before a bulk action.'; return }
    const selection = filters()
    if (action === 'publish' && !selection.source_revision_id) { data.error = 'Choose a single source version before publishing matching entries.'; return }
    const intent: WorldInfoBulkRequest = { action, filters: selection, ...(action === 'set_group' ? { group_name: group } : action === 'publish' ? {} : { tags }) }
    const signature = JSON.stringify(selection)
    const token = ++bulkRevision
    const result = await request('bulk-preview', api => api.previewBulk(intent))
    if (!result || token !== bulkRevision || signature !== JSON.stringify(filters())) return
    data.bulkIntent = copy(intent)
    data.bulkPreview = result
  }
  function bulkSelection(): WorldInfoBulkSelection | null {
    return data.bulkIntent && data.bulkPreview ? copy({ intent: data.bulkIntent, preview: data.bulkPreview }) : null
  }
  async function applyBulk(selection: WorldInfoBulkSelection) {
    const token = scopeRevision
    if (data.draft && JSON.stringify(data.draft) !== data.baseline) { data.error = 'Save or discard the entry draft before applying changes.'; return }
    const ok = await mutate('Applying confirmed changes…', api => api.applyBulk({ ...selection.intent, selection_hash: selection.preview.selection_hash }))
    if (token !== scopeRevision) return
    data.bulkPreview = null; data.bulkIntent = null
    if (!ok) return
    data.message = 'Confirmed changes saved for the matching entries in this session. Indexing is updated separately.'
    data.draft = null; data.baseline = ''
    await loadEntries(data.offset)
    if (token !== scopeRevision) return
    await refresh()
    if (token !== scopeRevision) return
    await loadFacets()
  }
  function reset() { revision++; scopeRevision++; clearBulk(); Object.assign(data, worldInfoCatalogState()) }
  return { filters, loadEntries, loadFacets, search, selectGroup, previewBulk, bulkSelection, applyBulk, clearBulk, hasPendingFilters, reset }
}
