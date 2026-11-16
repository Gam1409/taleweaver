import type { WorldBrief } from '@/types/worldBrief'
export type { WorldBrief, WorldReference } from '@/types/worldBrief'

export function emptyWorldBrief(): WorldBrief {
  return { setting: '', history: '', opening: '', characters: '', world_rules: '', open_threads: '', references: [] }
}

export function hasWorldBrief(brief: WorldBrief): boolean {
  return Object.entries(brief).some(([key, value]) => key === 'references'
    ? brief.references.some(source => source.url.trim() || source.excerpt.trim() || source.note.trim())
    : String(value).trim().length > 0)
}

export function worldBriefPayload(brief: WorldBrief): WorldBrief | undefined {
  if (!hasWorldBrief(brief)) return undefined
  return { ...brief, references: brief.references.filter(source => source.url.trim() || source.excerpt.trim() || source.note.trim()).map(source => ({ ...source })) }
}

export function briefTitle(brief: WorldBrief): string {
  return (brief.setting || brief.opening || brief.history || 'A New Adventure').split('\n')[0].slice(0, 45)
}
