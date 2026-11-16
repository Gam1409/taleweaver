/** Resolve display labels within the supplied session cast, without creating identities. */
interface NpcIdentity {
  id?: unknown
  name?: unknown
  entity_type?: unknown
  aliases?: unknown
  metadata_json?: { npc_journal?: { aliases?: unknown } }
}

function normalized(value: unknown): string {
  return typeof value === 'string' ? value.normalize('NFKC').trim().toLowerCase().replace(/\s+/gu, ' ') : ''
}

function nameParts(value: unknown): string[] {
  return normalized(value).match(/[\p{L}\p{M}\p{N}]+(?:['’-][\p{L}\p{M}\p{N}]+)*/gu) ?? []
}

function aliases(record: NpcIdentity): string[] {
  return [record.aliases, record.metadata_json?.npc_journal?.aliases]
    .flatMap(values => Array.isArray(values) ? values.filter((value): value is string => typeof value === 'string') : [])
}

function unique<T extends NpcIdentity>(matches: readonly T[]): T | null {
  const records = new Map<string | T, T>()
  for (const record of matches) {
    const key = typeof record.id === 'string' && record.id ? record.id : record
    if (!records.has(key)) records.set(key, record)
  }
  return records.size === 1 ? records.values().next().value! : null
}

export function resolveNpcIdentity<T extends NpcIdentity>(label: string, records: readonly T[]): T | null {
  const name = normalized(label)
  if (!name) return null
  const characters = records.filter(record => !record.entity_type || normalized(record.entity_type) === 'npc')
  const parts = nameParts(label)
  const stages: ((record: T) => boolean)[] = [
    record => normalized(record.id) === name,
    record => normalized(record.name) === name,
    record => aliases(record).some(alias => normalized(alias) === name),
    record => {
      const full = nameParts(record.name)
      return parts.length > 0 && parts.length <= full.length &&
        full.some((_, start) => parts.every((part, index) => full[start + index] === part))
    },
  ]
  for (const match of stages) {
    const candidates = characters.filter(match)
    if (candidates.length) return unique(candidates)
  }
  return null
}

function metadataRecords<T extends NpcIdentity>(metadata: Record<string, T> = {}) {
  return Object.entries(metadata)
    .filter(([, value]) => value && typeof value === 'object')
    .map(([key, value]) => ({
      ...value,
      id: typeof value.id === 'string' && value.id ? value.id : key,
      name: value.name || key,
      aliases: [key, ...(Array.isArray(value.aliases) ? value.aliases : [])],
    }))
}

export function resolveNpcMetadata(nameOrId: string, metadataMap?: Record<string, any>) {
  return resolveNpcIdentity(nameOrId, metadataRecords(metadataMap || {}))
}

export function resolveNpc(name: string, entities: any[] = [], metadataMap?: Record<string, any>) {
  const cast = entities || []
  const metadata = metadataRecords(metadataMap || {})
  const identity = resolveNpcIdentity(name, [...cast, ...metadata])
  if (!identity) return null
  const norm = normalized(name)
  const foundEntity = cast.find(entity => entity === identity ||
    (identity.id && entity.id === identity.id && normalized(entity.entity_type) === 'npc'))
  const meta = metadata.find(record => record.id === identity.id)
  if (foundEntity || meta) {
    return {
      id: foundEntity?.id || meta?.id || norm,
      entity_type: foundEntity?.entity_type || meta?.entity_type || 'NPC',
      name: foundEntity?.name || meta?.name || name,
      description: foundEntity?.description || meta?.description || meta?.backstory || 'A character in this adventure.',
      image_url: foundEntity?.image_url || meta?.image_url || null,
      role: foundEntity?.role || meta?.role || null,
      hp: foundEntity?.hp != null ? foundEntity.hp : meta?.hp != null ? meta.hp : 100,
      max_hp: foundEntity?.max_hp != null ? foundEntity.max_hp : meta?.max_hp != null ? meta.max_hp : 100,
      stamina: foundEntity?.stamina != null ? foundEntity.stamina : meta?.stamina != null ? meta.stamina : 50,
      max_stamina: foundEntity?.max_stamina != null ? foundEntity.max_stamina : meta?.max_stamina != null ? meta.max_stamina : 50,
      mana: foundEntity?.mana != null ? foundEntity.mana : meta?.mana != null ? meta.mana : 50,
      max_mana: foundEntity?.max_mana != null ? foundEntity.max_mana : meta?.max_mana != null ? meta.max_mana : 50,
      inventory: Array.isArray(foundEntity?.inventory) ? foundEntity.inventory : Array.isArray(meta?.inventory) ? meta.inventory : [],
      stat_modifiers: foundEntity?.stat_modifiers || meta?.stat_modifiers || {},
      metadata_json: foundEntity?.metadata_json || meta?.metadata_json || {},
    }
  }
  return null
}

