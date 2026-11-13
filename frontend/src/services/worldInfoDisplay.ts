import type { WorldInfoIndex, WorldInfoLimits, WorldInfoSource, WorldInfoSourceDetails } from '@/types/worldInfo'

export const worldInfoKinds = { background_lore: 'Background lore', world_fact: 'World fact', reported_claim: 'Reported claim', rumor: 'Rumor', news: 'News', character_knowledge: 'Recollection / character knowledge', authored_event: 'Authored event' }
export const worldInfoAudiences = { narrator_only: 'Narrator only', common_knowledge: 'Common knowledge', restricted: 'Selected characters' }
export const infoCount = (value: number | null | undefined) => value == null ? '—' : value.toLocaleString()
export const worldInfoTagLabel = (tag: string) => tag.startsWith('#') ? tag : `#${tag}`
export function worldInfoSourceOptions(sources: WorldInfoSource[], detail: WorldInfoSourceDetails | null, active: boolean) {
  const options: { id: string; title: string }[] = []
  for (const source of sources) {
    const ordinal = active ? source.published_revision : source.job.number
    const accepted = source.published_revision_id ?? (source.published_revision === source.job.number ? source.job.id : detail?.source.id === source.id ? detail.revisions.find(job => job.number === source.published_revision)?.id : undefined)
    const id = active ? accepted : source.job.id
    if (id) options.push({ id, title: `${source.title || source.filename} · version ${ordinal}${active ? ' · Accepted' : ''}` })
  }
  if (active || !detail) return options
  for (const job of detail.revisions) {
    if (options.some(value => value.id === job.id)) continue
    options.push({ id: job.id, title: `${detail.source.title || detail.source.filename} · version ${job.number}` })
  }
  return options
}
export function indexMessage(index: WorldInfoIndex): string {
  if (!index.enabled) return 'Memory recall is disabled. Accepted entries stay saved; enable recall in administrator settings to use retrieval.'
  if (index.paused) return 'Accepted entries are saved. Vector indexing is paused; lexical recall remains available.'
  if (index.status === 'error' || index.status === 'failed') return 'Accepted entries are saved. Vector indexing needs another attempt; lexical recall remains available.'
  if (index.indexed_revision < index.desired_revision) return 'Accepted entries are saved. Vector indexing is queued; lexical recall remains available.'
  return 'Accepted entries are saved. Memory indexing is up to date.'
}
export async function validateWorldInfoFile(file: File, limits: WorldInfoLimits): Promise<void> {
  if (!/\.(md|json)$/i.test(file.name)) throw new Error('Choose a Markdown (.md) or JSON (.json) file.')
  if (file.size > limits.max_source_bytes) throw new Error(`Choose a file of at most ${infoCount(limits.max_source_bytes)} bytes.`)
  const text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer())
  if (!text.trim()) throw new Error('The source file is empty.')
  let characters = 0
  for (const _character of text) {
    void _character
    characters++
    if (characters > limits.max_source_characters) throw new Error(`The source exceeds ${infoCount(limits.max_source_characters)} characters.`)
  }
  if (/\.json$/i.test(file.name)) {
    try { JSON.parse(text) } catch { throw new Error('This JSON file could not be read. Check its syntax and try again.') }
  }
}
