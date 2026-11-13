import { computed, onScopeDispose, reactive, watch, type Ref } from 'vue'
import { createStatusPoller } from '@/services/statusPoller'
import { WorldInfoError, worldInfoService } from '@/services/worldInfoService'
import { validateWorldInfoFile } from '@/services/worldInfoDisplay'
import { useWorldInfoCatalog, worldInfoCatalogState } from './useWorldInfoCatalog'
import type { WorldInfoContent, WorldInfoEntry, WorldInfoEntrySummary, WorldInfoJob, WorldInfoSource, WorldInfoSourceDetails, WorldInfoState, WorldInfoTab } from '@/types/worldInfo'

const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value))
export function useWorldInfo(sessionId: Readonly<Ref<string>>) {
  const data = reactive({
    state: null as WorldInfoState | null, source: null as WorldInfoSourceDetails | null,
    job: null as WorldInfoJob | null, content: null as WorldInfoContent | null,
    tab: 'files' as WorldInfoTab, mobileDetail: false, error: '', message: '', busy: '',
    loading: false, entryLoading: false, offline: false, query: '', revisionFilter: '',
    entries: [] as WorldInfoEntrySummary[], total: 0, next: null as number | null,
    selected: [] as string[], draft: null as WorldInfoEntry | null, baseline: '',
    candidates: [] as WorldInfoEntrySummary[], candidateNext: null as number | null,
    candidateOffset: 0,
    ...worldInfoCatalogState(),
  })
  let epoch = 0
  let entryRevision = 0
  const requests = new Map<string, AbortController>()
  const dirty = computed(() => !!data.draft && JSON.stringify(data.draft) !== data.baseline)
  const selectedEntries = computed(() => data.entries.filter(entry => data.selected.includes(entry.id)))
  const selectedSource = computed(() => data.state?.sources.find(source => source.id === selectedEntries.value[0]?.source_id))
  const catalog = useWorldInfoCatalog(data, request, mutate, load)

  async function request<T>(key: string, action: (api: ReturnType<typeof worldInfoService>, signal: AbortSignal) => Promise<T>): Promise<T | undefined> {
    requests.get(key)?.abort()
    const controller = new AbortController()
    requests.set(key, controller)
    const token = epoch
    const sid = sessionId.value
    try {
      const result = await action(worldInfoService(sid, controller.signal), controller.signal)
      if (token === epoch && sid === sessionId.value && !controller.signal.aborted && requests.get(key) === controller) return result
    } catch (error) {
      if (token === epoch && !controller.signal.aborted) data.error = error instanceof WorldInfoError ? error.message : 'The request could not finish. Please retry.'
    } finally {
      if (requests.get(key) === controller) requests.delete(key)
    }
  }
  function applyState(state: WorldInfoState) {
    if (state.session_id !== sessionId.value) return
    data.state = state
    data.offline = false
    const source = state.sources.find(value => value.id === data.source?.source.id)
    if (source && data.source) {
      data.source.source = source
      data.source.revisions = data.source.revisions.map(revision => revision.id === source.job.id ? source.job : revision)
    }
    const job = state.sources.find(value => value.job.id === data.job?.id)?.job
    if (job) data.job = job
  }
  const activeJobs = () => data.state?.sources.some(source => ['queued', 'processing'].includes(source.job.status)) ?? false
  const poller = createStatusPoller(async signal => {
    const token = epoch, sid = sessionId.value
    return { token, sid, state: await worldInfoService(sid, signal).state() }
  }, {
    onData: result => {
      if (result.token !== epoch || result.sid !== sessionId.value) return false
      const wasWorking = activeJobs()
      applyState(result.state)
      if (wasWorking && !activeJobs() && data.tab !== 'files') void Promise.all([catalog.loadEntries(data.offset), catalog.loadFacets()])
      return activeJobs()
    },
    onPaused: () => { data.offline = true },
    onMissing: () => { data.offline = true; data.error = 'This session is no longer available.' },
  })
  async function load() {
    data.loading = true
    const token = epoch
    const state = await request('state', api => api.state())
    if (token !== epoch) return
    data.loading = false
    if (!state) return
    applyState(state)
    if (activeJobs()) void poller.start()
  }
  async function loadEntries(more = false) {
    await catalog.loadEntries(more ? data.next ?? data.offset : 0)
  }
  async function changeTab(tab: WorldInfoTab) {
    requests.get('entry')?.abort()
    requests.get('candidates')?.abort()
    requests.get('entries')?.abort()
    data.tab = tab
    data.mobileDetail = false
    data.draft = null
    data.baseline = ''
    data.entries = []
    data.selected = []
    data.query = ''
    data.revisionFilter = ''
    Object.assign(data, worldInfoCatalogState())
    if (tab !== 'files') await catalog.search()
  }
  async function openSource(id: string) {
    requests.get('content')?.abort()
    data.error = ''
    data.mobileDetail = true
    data.content = null
    data.source = null
    data.job = null
    const source = await request('source', api => api.source(id))
    if (!source) return
    data.source = source
    data.job = source.source.job
  }
  async function chooseRevision(job: WorldInfoJob) {
    requests.get('content')?.abort()
    data.job = job
    data.content = null
  }
  async function previewSource(offset = 0) {
    if (!data.job) return
    const id = data.job.id
    const result = await request('content', api => api.content(id, offset))
    if (result && result.id === data.job?.id) data.content = result
  }
  async function reviewRevision(job: WorldInfoJob) {
    const token = epoch
    await changeTab('review')
    if (token !== epoch || data.tab !== 'review') return
    data.revisionFilter = job.id
    await catalog.search()
  }
  async function openEntry(id: string) {
    const revision = ++entryRevision
    data.error = ''
    data.message = ''
    data.entryLoading = true
    data.draft = null
    data.baseline = ''
    const result = await request('entry', api => api.entry(id))
    if (revision !== entryRevision) return
    data.entryLoading = false
    if (!result) return
    data.draft = copy(result)
    data.baseline = JSON.stringify(result)
    await loadCandidates()
  }
  function closeEntry() {
    entryRevision++
    requests.get('entry')?.abort()
    requests.get('candidates')?.abort()
    data.draft = null; data.baseline = ''; data.entryLoading = false
  }
  function discardEntry() { if (data.baseline) data.draft = copy(JSON.parse(data.baseline)) }
  async function loadCandidates(query = '', direction?: 'next' | 'previous') {
    const offset = direction === 'next' ? data.candidateNext ?? data.candidateOffset : direction === 'previous' ? Math.max(0, data.candidateOffset - 50) : 0
    const result = await request('candidates', api => api.entries('all', query, '', offset))
    if (!result) return
    data.candidates = result.entries
    data.candidateNext = result.next_offset
    data.candidateOffset = offset
  }
  async function mutate(label: string, action: (api: ReturnType<typeof worldInfoService>, signal: AbortSignal) => Promise<unknown>, retainBusy = false) {
    if (data.busy) return false
    data.busy = label
    data.error = ''
    data.message = ''
    const token = epoch
    const result = await request('mutation', action)
    if (token !== epoch) return false
    if (!retainBusy || result === undefined) data.busy = ''
    return result !== undefined
  }
  async function upload(file: File, title: string, replacement?: WorldInfoSource) {
    if (!data.state) return
    const limits = copy(data.state.limits)
    const token = epoch
    try { await validateWorldInfoFile(file, limits) } catch {
      if (token === epoch) data.error = 'Choose valid UTF-8 Markdown or JSON within the displayed file and character limits.'
      return
    }
    if (token !== epoch) return
    let result: { source: WorldInfoSource; revision: WorldInfoJob; duplicate: boolean } | undefined
    const ok = await mutate('Uploading and analysing…', async (api, signal) => {
      result = await api.upload(file, title, replacement)
      signal.throwIfAborted()
      if (result.revision.can_start && (result.revision.total_batches ?? 0) <= 16) await api.process(result.revision)
      return result
    })
    if (token !== epoch) return
    if (!ok || !result) { await load(); return }
    data.message = result.duplicate ? 'This file is already saved. Its existing processing progress is kept.' : 'Source saved. Review the proposed entries before publishing.'
    if (result.revision.can_start && (result.revision.total_batches ?? 0) > 16) data.message = 'Large source saved without starting analysis. Review the workload below and choose Start analysis when ready.'
    await load()
    if (token !== epoch) return
    await openSource(result.source.id)
  }
  async function control(job: WorldInfoJob, action: 'process' | 'cancel') {
    const token = epoch
    const ok = await mutate(action === 'cancel' ? 'Cancelling processing…' : 'Starting processing…', api => api[action](job))
    if (!ok) return
    data.message = action === 'cancel' ? 'Processing cancelled. Saved draft work is kept.' : 'Processing continues from this revision’s saved progress.'
    await load()
    if (token !== epoch) return
    if (data.source) await openSource(data.source.source.id)
  }
  async function saveEntry() {
    if (!data.draft || data.busy) return false
    const draft = copy(data.draft)
    const token = epoch
    let saved: WorldInfoEntry | undefined
    const ok = await mutate('Saving entry…', async api => {
      saved = await api.save(draft)
      return saved
    }, true)
    try {
      if (!ok || !saved) return false
      data.draft = copy(saved)
      data.baseline = JSON.stringify(saved)
      data.message = 'Entry saved. Indexing is updated separately.'
      await refreshEntries()
      return token === epoch
    } finally {
      if (token === epoch) data.busy = ''
    }
  }
  async function publish(selection?: { source: WorldInfoSource; entries: WorldInfoEntrySummary[] }) {
    const source = selection?.source ?? selectedSource.value
    const entries = selection?.entries ?? selectedEntries.value
    if (!source || !entries.length) return
    const revision = entries[0]!.source_revision_id
    if (entries.some(entry => entry.source_revision_id !== revision)) { data.error = 'Choose entries from one source version at a time.'; return }
    if (dirty.value) { data.error = 'Save or discard the entry draft before publishing.'; return }
    const token = epoch
    const ok = await mutate('Publishing selected entries…', api => api.publish(source, revision, entries))
    if (!ok) return
    data.message = 'Selected entries are accepted for this session. Indexing is updated separately.'
    data.selected = []
    data.draft = null
    if (token === epoch) await refreshEntries()
  }
  async function removeSource(source: WorldInfoSource) {
    if (!await mutate('Deleting source…', api => api.removeSource(source))) return
    data.source = null; data.job = null; data.content = null; data.mobileDetail = false
    data.message = 'Source and linked entries removed from this session.'
    await load()
  }
  async function removeEntry() {
    if (!data.draft) return false
    const token = epoch
    const entry = copy(data.draft)
    if (!await mutate('Deleting entry…', api => api.removeEntry(entry))) return false
    closeEntry()
    data.message = 'Entry removed. Its derived memory is invalidated.'
    await refreshEntries()
    return token === epoch
  }
  async function unpublish() {
    if (!data.draft) return false
    const token = epoch
    const entry = copy(data.draft)
    if (!await mutate('Removing entry from recall…', api => api.unpublish(entry))) return false
    closeEntry()
    await refreshEntries()
    return token === epoch
  }
  async function rebuild() {
    if (!await mutate('Queuing session index…', api => api.rebuild())) return
    data.message = 'Index rebuild queued for this session only.'
    await load()
  }
  async function refreshEntries() {
    const token = epoch
    await Promise.all([catalog.loadEntries(data.offset), catalog.loadFacets()])
    if (token === epoch) await load()
  }
  function reset() {
    epoch++
    entryRevision++
    catalog.reset()
    poller.stop()
    requests.forEach(controller => controller.abort())
    requests.clear()
    Object.assign(data, { state: null, source: null, job: null, content: null, draft: null, baseline: '', entries: [], candidates: [], selected: [], tab: 'files', mobileDetail: false, query: '', revisionFilter: '', busy: '', error: '', message: '', loading: false, entryLoading: false, offline: false, total: 0, next: null, candidateNext: null, candidateOffset: 0 })
  }
  watch(sessionId, () => { reset(); if (sessionId.value) void load() }, { immediate: true, flush: 'sync' })
  onScopeDispose(reset)
  return { data, catalog, dirty, selectedEntries, selectedSource, load, loadEntries, changeTab, openSource, chooseRevision, previewSource, reviewRevision, openEntry, closeEntry, discardEntry, loadCandidates, upload, control, saveEntry, publish, removeSource, removeEntry, unpublish, rebuild }
}
export type WorldInfoController = ReturnType<typeof useWorldInfo>
