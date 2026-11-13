import type { WorldInfoBulkRequest, WorldInfoEntry, WorldInfoFilters, WorldInfoJob, WorldInfoKind, WorldInfoSource, WorldInfoState } from '../../src/types/worldInfo'

export function createWorldInfoFixture(recordCount = 3) {
  const requests: { path: string; method: string }[] = [], writes: { path: string; body: unknown }[] = []
  let failCancel = false, failSave = false
  const worlds = new Map<string, ReturnType<typeof makeWorld>>()
  function makeWorld(sid: string) {
    const quote = 'The harbour beacon was rebuilt after the winter storm.'
    const baseText = `# The coastal archive\n\n${quote}\n\n<SCRIPT>window.worldInfoInjected = true</SCRIPT>\n<img src=x onerror="window.worldInfoInjected=true">\n[An inert link](https://example.invalid/)\n`
    const content = recordCount > 100 ? baseText + 'The coastal archive preserves maps, customs and harbour records.\n'.repeat(3000) : baseText
    const chars = Array.from(content).length, bytes = new TextEncoder().encode(content).length
    const job: WorldInfoJob = { id: 'revision-2', source_id: 'source-1', number: 2, status: recordCount > 100 ? 'review' : 'processing', control_version: 4, cursor: recordCount > 100 ? 24 : 2, total_batches: recordCount > 100 ? 24 : 3, processed_characters: recordCount > 100 ? chars : Math.floor(chars * 2 / 3), input_bytes: bytes, input_characters: chars, facts_count: 5, entries_count: 2, entries_bytes: 736, entries_characters: 680, attempts: 1, processing_language: 'English', last_error_code: null, can_start: false, can_resume: false, can_cancel: recordCount <= 100 }
    const source: WorldInfoSource = { id: 'source-1', title: 'The coastal archive', filename: 'coastal-archive.md', format: 'md', version: 6, current_revision: 2, published_revision: 1, published_revision_id: 'revision-1', revision_count: 2, active_entries: 1, draft_entries: 2, job }
    const secondJob = { ...job, id: 'garden-revision', source_id: 'source-2', number: 1, status: 'cancelled', cursor: 1, total_batches: 4, can_resume: true, can_cancel: false }
    const state: WorldInfoState = { session_id: sid, sources: [source, { ...source, id: 'source-2', title: 'Notes from the winter garden', filename: 'winter-garden.json', current_revision: 1, published_revision: null, published_revision_id: null, revision_count: 1, active_entries: 0, draft_entries: 0, job: secondJob }], characters: [{ id: 'MIRA', name: 'Mira · Archivist' }, { id: 'OWEN', name: 'Owen · Harbour keeper' }], index: { enabled: true, paused: true, status: 'paused', desired_revision: 6, indexed_revision: 5 }, limits: { max_source_bytes: 8388608, max_source_characters: 4000000, max_sources: 32, max_source_revisions: 8, max_session_source_bytes: 16777216, max_entry_characters: 2400, max_tags: 12, max_tag_characters: 48, max_known_by: 32, max_relations: 12, max_entry_title_characters: 160, max_entry_summary_characters: 500, max_fact_characters: 500, max_relation_note_characters: 160, max_entries: 10000, max_facts: 80000, max_group_characters: 80 } }
    const entry: WorldInfoEntry = { id: 'entry-beacon', source_id: source.id, source_revision_id: job.id, source_filename: source.filename, source_revision_number: 2, version: 2, title: 'The harbour beacon', summary: 'A reliable light, rebuilt by the coast’s craftspeople after the winter storm.', group_name: 'Coastal history', kind: 'background_lore', audience: 'narrator_only', known_by: [], tags: ['coastal-history', 'lighthouse'], status: 'draft', is_active: false, edited: false, facts_count: 2, character_count: 340, byte_count: 368, facts: [{ id: 'fact-beacon', text: quote, original_text: quote, edited: false, evidence: [{ passage_id: 'passage-1', pointer: null, start: 27, end: 80, quote, source_hash: 'fictional-source-hash' }] }, { id: 'fact-keepers', text: 'The harbour keepers maintain the light through the colder months.', original_text: 'The harbour keepers maintain the light through the colder months.', edited: false, evidence: [{ passage_id: 'passage-2', pointer: null, start: 81, end: 144, quote: 'The harbour keepers maintain the light through the colder months.', source_hash: 'fictional-source-hash' }] }], relations: [] }
    const entries: WorldInfoEntry[] = [entry, { ...structuredClone(entry), id: 'entry-route', title: 'The old coastal path', summary: 'A stone path connects the archive to the harbour.', group_name: 'Places & routes', tags: ['geography'], facts: [{ ...structuredClone(entry.facts[0]!), id: 'fact-route', text: 'The old path follows the cliffs.', original_text: 'The old path follows the cliffs.' }] }, { ...structuredClone(entry), id: 'entry-active', source_revision_id: 'revision-1', source_revision_number: 1, title: 'The archive reading room', group_name: 'Archives', status: 'published', is_active: true }]
    const groups = ['Coastal history', 'Places & routes', 'People & customs', 'Trade & crafts', 'Rumors & reports', 'Archives', 'Gardens', 'Maritime traditions']
    const kinds: WorldInfoKind[] = ['world_fact', 'background_lore', 'rumor', 'news', 'reported_claim']
    for (let i = 3; i < recordCount; i++) {
      const number = String(i + 1).padStart(5, '0')
      entries.push({ ...structuredClone(entry), id: `entry-${number}`, title: `Coastal record ${number} · ${groups[i % groups.length]}`, summary: `Harbour archive notes about coastal trade, places and customs, record ${number}.`, group_name: groups[i % groups.length], kind: kinds[i % kinds.length]!, tags: ['coast', `year-${i % 300}`], facts: entry.facts.map((fact, j) => ({ ...structuredClone(fact), id: `fact-${number}-${j}` })), source_revision_id: i % 3 === 0 ? 'revision-1' : 'revision-2', source_revision_number: i % 3 === 0 ? 1 : 2, status: i % 3 === 0 ? 'published' : 'draft', is_active: i % 3 === 0 })
    }
    return { state, entries, revisions: [job, { ...job, id: 'revision-1', number: 1, status: 'review', cursor: job.total_batches ?? 3, processed_characters: chars, can_cancel: false }, secondJob], contents: new Map([['revision-2', content], ['revision-1', baseText], ['garden-revision', '{}']]) }
  }
  function world(sid: string) { if (!worlds.has(sid)) worlds.set(sid, makeWorld(sid)); return worlds.get(sid)! }
  const json = (value: unknown, status = 200) => Response.json(value, { status })
  function totals(data: ReturnType<typeof makeWorld>) {
    data.entries.forEach(entry => { entry.facts_count = entry.facts.length; entry.is_active = entry.status === 'published' && data.state.sources.find(source => source.id === entry.source_id)?.published_revision === entry.source_revision_number })
    for (const revision of data.revisions) { const entries = data.entries.filter(entry => entry.source_revision_id === revision.id); revision.entries_count = entries.length; revision.facts_count = entries.reduce((n, entry) => n + entry.facts.length, 0); revision.entries_bytes = entries.reduce((n, entry) => n + entry.byte_count, 0); revision.entries_characters = entries.reduce((n, entry) => n + entry.character_count, 0) }
    for (const source of data.state.sources) { source.active_entries = data.entries.filter(entry => entry.source_id === source.id && entry.is_active).length; source.draft_entries = data.entries.filter(entry => entry.source_id === source.id && entry.status === 'draft').length }
    data.state.totals = { entries: data.entries.length, facts: data.entries.reduce((n, entry) => n + entry.facts.length, 0), active_entries: data.entries.filter(entry => entry.is_active).length, draft_entries: data.entries.filter(entry => entry.status === 'draft').length, archived_entries: data.entries.filter(entry => entry.status === 'archived').length, sources: data.state.sources.length, source_revisions: data.revisions.length, source_bytes: data.revisions.reduce((n, revision) => n + revision.input_bytes, 0), entries_bytes: data.entries.reduce((n, entry) => n + entry.byte_count, 0), entries_characters: data.entries.reduce((n, entry) => n + entry.character_count, 0) }
  }
  function filtered(data: ReturnType<typeof makeWorld>, filters: Partial<WorldInfoFilters>, facets = false) {
    const terms = (filters.query ?? '').toLocaleLowerCase().trim().split(/\s+/u).filter(Boolean)
    let values = data.entries.filter(entry => (!filters.source_revision_id || entry.source_revision_id === filters.source_revision_id) && (filters.view === 'all' || (filters.view === 'active' ? entry.is_active : entry.status === 'draft')) && terms.every(term => `${entry.title} ${entry.summary} ${entry.facts.map(fact => fact.text).join(' ')} ${entry.group_name} ${entry.tags.join(' ')}`.toLocaleLowerCase().includes(term)))
    if (!facets) values = values.filter(entry => (filters.group_name == null || (entry.group_name ?? '') === filters.group_name) && (!filters.tag || entry.tags.includes(filters.tag)) && (!filters.kind || entry.kind === filters.kind))
    if (filters.sort === 'title_asc' || filters.sort === 'title_desc') values.sort((a, b) => a.title.localeCompare(b.title) * (filters.sort === 'title_desc' ? -1 : 1))
    if (filters.sort === 'oldest') values.reverse()
    if (filters.sort === 'source') values.sort((a, b) => a.source_filename.localeCompare(b.source_filename))
    return values
  }
  function hash(intent: WorldInfoBulkRequest, data: ReturnType<typeof makeWorld>) {
    const value = JSON.stringify([intent, filtered(data, intent.filters).map(entry => [entry.id, entry.version]), data.state.sources.map(source => source.version)])
    let result = 0; for (const char of value) result = (result * 31 + char.codePointAt(0)!) >>> 0
    return `fixture-${result.toString(16)}`
  }
  async function respond(url: string, options?: RequestInit): Promise<Response | null> {
    const match = url.match(/\/adventures\/([^/]+)\/world-info(.*)$/)
    if (!match) return null
    const sid = decodeURIComponent(match[1]!), raw = match[2] || '', path = raw.split('?')[0]!, params = new URLSearchParams(raw.split('?')[1]), method = options?.method || 'GET'
    const data = world(sid), body = typeof options?.body === 'string' ? JSON.parse(options.body) : options?.body
    requests.push({ path: `/adventures/${encodeURIComponent(sid)}/world-info${raw}`, method })
    if (method !== 'GET') writes.push({ path, body: body instanceof FormData ? { multipart: true, fields: [...body.keys()] } : body })
    if (!path) { totals(data); return json(data.state) }
    if (path === '/entries' || path === '/entries/facets') {
      const filters = Object.fromEntries(params) as unknown as WorldInfoFilters
      if (path.endsWith('/facets')) {
        const entries = filtered(data, filters, true), find = (params.get('facet_query') ?? '').toLowerCase()
        const facet = (labels: string[]) => { const counts = new Map<string, number>(); labels.forEach(name => counts.set(name, (counts.get(name) ?? 0) + 1)); const items = [...counts].filter(([name]) => name.toLowerCase().includes(find)).sort(([a], [b]) => a.localeCompare(b)).map(([name, count]) => ({ name, count })); return { items: items.slice(0, 100), total: items.length } }
        return json({ groups: facet(entries.map(entry => entry.group_name ?? '')), tags: facet(entries.flatMap(entry => entry.tags)), kinds: facet(entries.map(entry => entry.kind)) })
      }
      const entries = filtered(data, filters), offset = Number(params.get('offset') || 0), limit = Number(params.get('limit') || 50)
      return json({ entries: entries.slice(offset, offset + limit), total: entries.length, next_offset: offset + limit < entries.length ? offset + limit : null })
    }
    if (path.startsWith('/entries/bulk/')) {
      const { selection_hash: supplied, ...intent } = body
      const entries = filtered(data, intent.filters)
      if (path.endsWith('/preview')) return json({ action: intent.action, count: entries.length, facts_count: entries.reduce((n, entry) => n + entry.facts.length, 0), active_count: entries.filter(entry => entry.is_active).length, selection_hash: hash(intent, data), sample: entries.slice(0, 5), source_version: data.state.sources[0]?.version ?? null, source_revision_id: intent.filters.source_revision_id ?? null })
      if (supplied !== hash(intent, data)) return json({}, 409)
      if (intent.action === 'add_tags' && entries.some(entry => new Set([...entry.tags, ...intent.tags]).size > 12)) return json({}, 422)
      if (intent.action === 'publish') {
        const revision = data.revisions.find(value => value.id === intent.filters.source_revision_id)!, source = data.state.sources.find(value => value.id === revision.source_id)!
        data.entries.filter(entry => entry.source_id === source.id && entry.is_active && entry.source_revision_id !== revision.id).forEach(entry => { entry.is_active = false; entry.status = 'archived'; entry.version++ })
        source.published_revision = revision.number; source.published_revision_id = revision.id; source.version++
      }
      for (const entry of entries) {
        if (intent.action === 'set_group') entry.group_name = intent.group_name
        if (intent.action === 'add_tags') entry.tags = [...new Set([...entry.tags, ...intent.tags])]
        if (intent.action === 'remove_tags') entry.tags = entry.tags.filter(tag => !intent.tags.includes(tag))
        if (intent.action === 'publish') { entry.status = 'published'; entry.is_active = true }
        entry.version++
      }
      data.state.index.desired_revision++
      return json({ action: intent.action, matched: entries.length, changed: entries.length, index: data.state.index })
    }
    if ((path === '/sources' || /\/sources\/[^/]+\/revisions$/.test(path)) && method === 'POST') {
      const form = body as FormData, file = form.get('file') as File
      const replacing = path !== '/sources'
      let source = replacing ? data.state.sources.find(value => value.id === path.split('/')[2]) : undefined
      if (replacing && (!source || form.has('title') || String(source.version) !== form.get('expected_version'))) return json({}, 409)
      const content = await file.text(), characters = Array.from(content).length, number = (source?.current_revision ?? 0) + 1, id = `revision-upload-${data.revisions.length + 1}`
      const revision: WorldInfoJob = { ...data.revisions[0]!, id, source_id: source?.id ?? `source-${data.state.sources.length + 1}`, number, cursor: 0, status: 'uploaded', total_batches: Math.max(1, Math.ceil(characters / 8000)), processed_characters: 0, input_bytes: file.size, input_characters: characters, entries_count: 0, facts_count: 0, entries_bytes: 0, entries_characters: 0, can_start: true, can_cancel: false, can_resume: false }
      if (source) Object.assign(source, { job: revision, current_revision: number, revision_count: source.revision_count + 1, version: source.version + 1 })
      else { source = { id: revision.source_id, title: String(form.get('title') || file.name), filename: file.name, format: file.name.endsWith('.json') ? 'json' : 'md', version: 1, current_revision: number, published_revision: null, published_revision_id: null, revision_count: 1, active_entries: 0, draft_entries: 0, job: revision }; data.state.sources.push(source) }
      data.revisions.push(revision); data.contents.set(id, content)
      return json({ source, revision, duplicate: false })
    }
    if (path.startsWith('/sources/')) {
      const source = data.state.sources.find(value => value.id === path.split('/')[2])
      if (!source) return json({}, 404)
      if (method === 'DELETE') { data.state.sources = data.state.sources.filter(value => value.id !== source.id); data.entries = data.entries.filter(value => value.source_id !== source.id); return json({ deleted: true, index: data.state.index }) }
      return json({ source, revisions: data.revisions.filter(revision => revision.source_id === source.id) })
    }
    if (path.startsWith('/revisions/')) {
      const revision = data.revisions.find(value => value.id === path.split('/')[2]), source = data.state.sources.find(value => value.id === revision?.source_id)
      if (path.endsWith('/content')) { const characters = Array.from(data.contents.get(revision!.id) ?? ''), offset = Number(params.get('offset') || 0), end = Math.min(characters.length, offset + Number(params.get('limit') || 8000)); return json({ id: revision?.id, filename: source?.filename, format: source?.format, content: characters.slice(offset, end).join(''), content_hash: 'fictional-hash', input_bytes: revision?.input_bytes, input_characters: characters.length, offset, next_offset: end < characters.length ? end : null, total_characters: characters.length }) }
      if (path.endsWith('/cancel') && failCancel) return json({}, 503)
      if (revision && method === 'POST') { revision.status = path.endsWith('/cancel') ? 'cancelled' : 'review'; revision.can_resume = revision.status === 'cancelled'; revision.can_start = false; revision.can_cancel = false; revision.control_version++; if (!revision.can_resume) { revision.cursor = revision.total_batches; revision.processed_characters = revision.input_characters } }
      return json({ source, revision })
    }
    if (path === '/publish') {
      const revision = data.revisions.find(value => value.id === body.revision_id)!, source = data.state.sources.find(value => value.id === revision.source_id)!, replacing = source.published_revision !== revision.number
      if (replacing) data.entries.filter(entry => entry.source_id === source.id && entry.is_active).forEach(entry => { entry.is_active = false; entry.status = 'archived' })
      for (const selected of body.entries) { const entry = data.entries.find(entry => entry.id === selected.id)!; entry.is_active = true; entry.status = 'published' }
      source.published_revision = revision.number; source.published_revision_id = revision.id; source.version++; data.state.index.desired_revision++
      return json({ published: body.entries.length, replaced: replacing ? 1 : 0, source, index: data.state.index })
    }
    if (path.startsWith('/entries/')) {
      const id = path.split('/')[2], entry = data.entries.find(value => value.id === id)
      if (!entry) return json({}, 404)
      if (method === 'PUT') {
        if (failSave) return json({}, 409)
        const facts = body.facts.map((fact: { id: string; text: string }) => ({ ...entry.facts.find(value => value.id === fact.id), ...fact, edited: fact.text !== entry.facts.find(value => value.id === fact.id)?.original_text })), unresolved = (entry.unresolved_known_by ?? []).filter(id => body.known_by.includes(id) && !body.resolve_known_by.includes(id))
        Object.assign(entry, body, { facts, unresolved_known_by: unresolved, version: entry.version + 1, edited: true }); delete entry.resolve_known_by; data.state.index.desired_revision++
      }
      if (method === 'DELETE') { data.entries = data.entries.filter(value => value.id !== id); return json({ deleted: true, index: data.state.index }) }
      if (path.endsWith('/unpublish')) { entry.is_active = false; entry.status = 'draft' }
      return json(entry)
    }
    if (path === '/index/rebuild') { data.state.index.paused = false; return json({ index: data.state.index }) }
    return json({}, 404)
  }
  function setFirstEntryTags(sid: string, tags: string[]) { world(sid).entries[0]!.tags = [...tags] }
  return { requests, writes, respond, setFirstEntryTags, failCancel(value: boolean) { failCancel = value }, failSave(value: boolean) { failSave = value }, prepareDormant(sid: string) { const entry = world(sid).entries[0]!; entry.audience = 'restricted'; entry.known_by = ['UNAVAILABLE', 'MIRA']; entry.unresolved_known_by = ['MIRA'] }, removeSourceFromOverview(sid: string, id: string) { const value = world(sid); value.state.sources = value.state.sources.filter(source => source.id !== id) }, changeFirstEntry(sid: string) { world(sid).entries[0]!.version++ }, longEntryMetadata(sid: string) { const data = world(sid); data.entries[0]!.title = 'T'.repeat(160); const filename = 'f'.repeat(252) + '.md'; data.state.sources[0]!.filename = filename; data.entries.filter(entry => entry.source_id === 'source-1').forEach(entry => { entry.source_filename = filename }) } }
}
