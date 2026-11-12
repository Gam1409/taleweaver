import type { NpcCard, NpcJournalEntry } from '../../src/composables/useNpcJournal'
import type { NpcVisibleGarment } from '../../src/types/npcCurrentState'

/** Fictional observations for the existing character panel; no game data is loaded. */
export function createCharacterPanelFixture() {
  let showState = false
  const garment = (item_id: string, name: string, slot: string, layer: number): NpcVisibleGarment => ({
    item_id, name, description: name + ', neatly kept for everyday work.', image_url: null,
    layer, visible_regions: [], uncovered_regions: [], slots: [slot],
  })
  function card(id: string, shared = false): NpcCard {
    const mira = id === 'MIRA', name = mira ? 'Mira' : 'Owen'
    const general: NpcJournalEntry = { id: id + '-background', category: 'background', text: mira ? 'Mira keeps the archive and its coastal charts.' : 'Owen maintains the harbour lamps.', evidence: mira ? 'Mira introduced herself as the archivist.' : 'Owen described his work at the harbour.', source: 'observed' }
    const memory: NpcJournalEntry = { id: id + '-meeting', category: 'event', text: mira ? 'Mira showed Alex the sealed letter.' : 'Owen pointed out the lighthouse on the chart.', evidence: mira ? 'Mira: The letter is waiting on the table.' : 'Owen: The lighthouse mark is on the map, too.', source: 'observed' }
    return {
      id, name, description: mira ? 'A patient archivist who knows the coast through its maps and letters.' : 'A practical harbour keeper familiar with the local paths.',
      image_url: null, scene_id: 'ARCHIVE', aliases: [], narrative_role: 'major', introduction: name,
      entry_count: 2, entries: [shared ? memory : general], summary: [memory], overview: [general],
      history_counts: { general: 1, shared: 1 }, has_more: false, state_visible: showState,
      relationship: { status: 'friendly', source: 'observed', text: 'Offers to help Alex read the chart.', evidence: 'They examine the map together.' },
      current_state: {
        availability: 'present', game_minute: 1122, layout: { form: 'humanoid', silhouette: 'neutral' },
        clothing: { status: 'available', detail_limited: false, items: [
          garment(id + '-jacket', 'Work jacket', 'Chest', 3), garment(id + '-shirt', 'Linen shirt', 'Chest', 1),
          garment(id + '-trousers', 'Travel trousers', 'Legs', 2), garment(id + '-boots', 'Walking boots', 'Feet', 2),
        ] },
        conditions: { status: 'available', items: [{ id: id + '-fatigue', target_id: id, kind: 'other', part: 'overall', detail: 'A little tired after sorting the archive shelves, but ready to continue.', status: 'active', observation: 'visible', last_changed_minute: 1120 }] },
      },
    }
  }
  return {
    respond(path: string, method: string, body: any): Response | null {
      const url = new URL(path, window.location.origin)
      if (url.pathname.endsWith('/npc-card-settings')) {
        if (method === 'PATCH') showState = body?.show_state === true
        return Response.json({ show_state: showState })
      }
      if (url.pathname.endsWith('/npcs')) return Response.json({ characters: [card('MIRA'), card('OWEN')], pending: 0, failed: 0, learning: { phase: 'up_to_date', elapsed_seconds: 0 } })
      const id = url.pathname.split('/npcs/')[1]
      if (id === 'MIRA' || id === 'OWEN') return Response.json(card(id, url.searchParams.get('history') === 'shared'))
      return null
    },
  }
}
