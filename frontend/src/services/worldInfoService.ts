import { apiFetch } from '@/services/http'
import type { WorldInfoBulkPreview, WorldInfoBulkRequest, WorldInfoContent, WorldInfoEntries, WorldInfoEntry, WorldInfoFacets, WorldInfoFilters, WorldInfoIndex, WorldInfoJob, WorldInfoSource, WorldInfoSourceDetails, WorldInfoState } from '@/types/worldInfo'

export class WorldInfoError extends Error {
  constructor(public status: number) {
    super(status === 409 ? 'This information changed. Your draft is kept. Reload the latest version before trying again.'
      : status === 413 ? 'The file exceeds the allowed size. Choose a smaller file.'
      : status === 422 ? 'Check the file format, field limits and selected records, then try again.'
      : status === 404 ? 'This session or record is no longer available.'
      : status === 403 ? 'You do not have permission to change this session.'
      : 'The request could not finish. Your saved information is kept. Please retry.')
  }
}
export function worldInfoEntryPayload(entry: WorldInfoEntry) {
  return {
    version: entry.version, title: entry.title, summary: entry.summary, kind: entry.kind,
    audience: entry.audience, known_by: entry.audience === 'restricted' ? [...entry.known_by] : [],
    resolve_known_by: entry.audience === 'restricted' ? [...(entry.resolve_known_by ?? [])] : [],
    ...(entry.group_name === undefined ? {} : { group_name: entry.group_name }),
    tags: [...entry.tags], relations: entry.relations.map(value => ({ ...value })),
    facts: entry.facts.map(({ id, text }) => ({ id, text })),
  }
}
export function worldInfoService(sessionId: string, signal: AbortSignal) {
  const base = `/adventures/${encodeURIComponent(sessionId)}/world-info`
  async function request<T>(path = '', method = 'GET', body?: unknown): Promise<T> {
    const multipart = body instanceof FormData
    const response = await apiFetch(`${base}${path}`, {
      method, signal, includeJson: !multipart,
      ...(body === undefined ? {} : { body: multipart ? body : JSON.stringify(body) }),
    })
    if (!response.ok) throw new WorldInfoError(response.status)
    return response.json() as Promise<T>
  }
  const upload = (file: File, title: string, source?: WorldInfoSource) => {
    const body = new FormData()
    body.append('file', file)
    if (!source && title.trim()) body.append('title', title.trim())
    if (source) body.append('expected_version', String(source.version))
    return request<{ source: WorldInfoSource; revision: WorldInfoJob; duplicate: boolean }>(source ? `/sources/${encodeURIComponent(source.id)}/revisions` : '/sources', 'POST', body)
  }
  return {
    state: () => request<WorldInfoState>(), upload,
    source: (id: string) => request<WorldInfoSourceDetails>(`/sources/${encodeURIComponent(id)}`),
    content: (id: string, offset = 0) => request<WorldInfoContent>(`/revisions/${encodeURIComponent(id)}/content?offset=${offset}&limit=8000`),
    process: (job: WorldInfoJob) => request<{ source: WorldInfoSource; revision: WorldInfoJob }>(`/revisions/${encodeURIComponent(job.id)}/process`, 'POST', { control_version: job.control_version }),
    cancel: (job: WorldInfoJob) => request<{ source: WorldInfoSource; revision: WorldInfoJob }>(`/revisions/${encodeURIComponent(job.id)}/cancel`, 'POST', { control_version: job.control_version }),
    removeSource: (source: WorldInfoSource) => request<{ deleted: boolean; index: WorldInfoIndex }>(`/sources/${encodeURIComponent(source.id)}?version=${source.version}`, 'DELETE'),
    entries: (view: 'review' | 'active' | 'all', query = '', revision = '', offset = 0, filters?: WorldInfoFilters) => {
      const params = worldInfoFilterParams(filters ?? { view, query, source_revision_id: revision || undefined, sort: 'newest' })
      params.set('offset', String(offset)); params.set('limit', '50')
      return request<WorldInfoEntries>(`/entries?${params}`)
    },
    facets: (filters: WorldInfoFilters, query = '') => {
      const params = worldInfoFilterParams(filters)
      if (query) params.set('facet_query', query)
      return request<WorldInfoFacets>(`/entries/facets?${params}`)
    },
    previewBulk: (body: WorldInfoBulkRequest) => request<WorldInfoBulkPreview>('/entries/bulk/preview', 'POST', body),
    applyBulk: (body: WorldInfoBulkRequest & { selection_hash: string }) => request<{ action: string; matched: number; changed: number; index: WorldInfoIndex }>('/entries/bulk/apply', 'POST', body),
    entry: (id: string) => request<WorldInfoEntry>(`/entries/${encodeURIComponent(id)}`),
    save: (entry: WorldInfoEntry) => request<WorldInfoEntry>(`/entries/${encodeURIComponent(entry.id)}`, 'PUT', worldInfoEntryPayload(entry)),
    removeEntry: (entry: WorldInfoEntry) => request<{ deleted: boolean; index: WorldInfoIndex }>(`/entries/${encodeURIComponent(entry.id)}?version=${entry.version}`, 'DELETE'),
    unpublish: (entry: WorldInfoEntry) => request<WorldInfoEntry>(`/entries/${encodeURIComponent(entry.id)}/unpublish`, 'POST', { version: entry.version }),
    publish: (source: WorldInfoSource, revisionId: string, entries: { id: string; version: number }[]) => request<{ published: number; replaced: number; source: WorldInfoSource; index: WorldInfoIndex }>('/publish', 'POST', { revision_id: revisionId, source_version: source.version, entries: entries.map(({ id, version }) => ({ id, version })) }),
    rebuild: () => request<{ index: WorldInfoIndex }>('/index/rebuild', 'POST'),
  }
}
export function worldInfoFilterParams(filters: WorldInfoFilters): URLSearchParams {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null) params.set(key, String(value))
  }
  return params
}
export type WorldInfoApi = ReturnType<typeof worldInfoService>
export type WorldInfoRequest = <T>(key: string, action: (api: WorldInfoApi, signal: AbortSignal) => Promise<T>) => Promise<T | undefined>
