export type WorldInfoKind = 'background_lore' | 'reported_claim' | 'character_knowledge' | 'authored_event' | 'world_fact' | 'rumor' | 'news'
export type WorldInfoAudience = 'narrator_only' | 'common_knowledge' | 'restricted'
export type WorldInfoTab = 'files' | 'review' | 'active'
export interface WorldInfoIndex {
  enabled: boolean
  paused: boolean
  status: string
  desired_revision: number
  indexed_revision: number
}
export interface WorldInfoJob {
  id: string
  source_id: string
  number: number
  status: string
  control_version: number
  cursor: number
  total_batches: number | null
  processed_characters: number
  input_bytes: number
  input_characters: number
  facts_count: number
  entries_count: number
  entries_bytes: number
  entries_characters: number
  attempts: number
  processing_language: string | null
  last_error_code: string | null
  can_start: boolean
  can_resume: boolean
  can_cancel: boolean
}
export interface WorldInfoSource {
  id: string
  title: string
  filename: string
  format: string
  version: number
  current_revision: number
  published_revision: number | null
  published_revision_id?: string | null
  revision_count: number
  active_entries: number
  draft_entries: number
  job: WorldInfoJob
}
export interface WorldInfoEvidence {
  passage_id: string
  pointer: string | null
  start: number
  end: number
  quote: string
  source_hash: string
}
export interface WorldInfoFact {
  id: string
  text: string
  original_text: string
  edited: boolean
  evidence: WorldInfoEvidence[]
}
export interface WorldInfoRelation {
  target_id: string
  kind: 'related' | 'supports' | 'contradicts' | 'part_of'
  note: string
}
export interface WorldInfoEntrySummary {
  id: string
  source_id: string
  source_revision_id: string
  source_filename: string
  source_revision_number: number
  version: number
  title: string
  summary: string
  kind: WorldInfoKind
  audience: WorldInfoAudience
  known_by: string[]
  tags: string[]
  group_name?: string
  status: string
  is_active: boolean
  edited: boolean
  facts_count: number
  character_count: number
  byte_count: number
}
export interface WorldInfoEntry extends WorldInfoEntrySummary {
  facts: WorldInfoFact[]
  relations: WorldInfoRelation[]
  unresolved_known_by?: string[]
  resolve_known_by?: string[]
}
export interface WorldInfoLimits {
  max_source_bytes: number
  max_source_characters: number
  max_sources: number
  max_source_revisions: number
  max_session_source_bytes: number
  max_entry_characters: number
  max_tags: number
  max_tag_characters: number
  max_known_by: number
  max_relations: number
  max_entry_title_characters?: number
  max_entry_summary_characters?: number
  max_fact_characters?: number
  max_relation_note_characters?: number
  max_entries?: number
  max_facts?: number
  max_group_characters?: number
}
export interface WorldInfoState {
  session_id: string
  sources: WorldInfoSource[]
  characters: { id: string; name: string }[]
  index: WorldInfoIndex
  limits: WorldInfoLimits
  totals?: { entries: number; facts: number; active_entries: number; draft_entries: number; archived_entries: number; sources: number; source_revisions: number; source_bytes: number; entries_bytes: number; entries_characters: number }
}
export interface WorldInfoEntries {
  entries: WorldInfoEntrySummary[]
  total: number
  next_offset: number | null
}
export interface WorldInfoSourceDetails { source: WorldInfoSource; revisions: WorldInfoJob[] }
export interface WorldInfoContent {
  id: string
  filename: string
  format: string
  content: string
  content_hash: string
  input_bytes: number
  input_characters: number
  offset?: number
  next_offset?: number | null
  total_characters?: number
}
export interface WorldInfoFilters {
  view: 'review' | 'active' | 'all'
  source_revision_id?: string | null
  query?: string
  group_name?: string | null
  tag?: string | null
  kind?: WorldInfoKind | null
  sort: 'newest' | 'oldest' | 'title_asc' | 'title_desc' | 'source'
}
export interface WorldInfoFacet { items: { name: string; count: number }[]; total: number }
export interface WorldInfoFacets { groups: WorldInfoFacet; tags: WorldInfoFacet; kinds: WorldInfoFacet }
export interface WorldInfoBulkRequest {
  action: 'set_group' | 'add_tags' | 'remove_tags' | 'publish'
  filters: WorldInfoFilters
  group_name?: string
  tags?: string[]
}
export interface WorldInfoBulkPreview {
  action: WorldInfoBulkRequest['action']
  count: number
  facts_count: number
  active_count: number
  selection_hash: string
  sample: WorldInfoEntrySummary[]
  source_version: number | null
  source_revision_id: string | null
}
