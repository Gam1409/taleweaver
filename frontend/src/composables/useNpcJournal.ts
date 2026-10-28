import { onScopeDispose, ref, watch, type Ref } from 'vue'
import { authState } from '@/store/auth'

export type NpcAttitude = 'unknown' | 'love' | 'trust' | 'friendly' | 'neutral' | 'suspicion' | 'hostility' | 'fear' | 'mixed'

export interface NpcRelationship {
  status: NpcAttitude
  source: 'observed' | 'claimed' | null
  text: string | null
  evidence: string | null
  recorded_at?: string | null
}

export interface NpcJournalEntry {
  id: string
  category: string
  topic?: string
  text: string
  evidence: string
  source: 'observed' | 'claimed'
  scene_id?: string
  recorded_at?: string
  player_attitude?: NpcAttitude | null
}

export interface NpcInsights {
  available: boolean
  relationship: { trust: number; affinity: number; respect: number; tension: number } | null
  emotion: string | null
  evidence: string | null
  source_message_id: string | null
}

export type NpcHistoryKind = 'all' | 'general' | 'shared'

export interface NpcCard {
  narrative_role?: 'supporting' | 'major'
  id: string
  name: string
  description: string
  image_url: string | null
  scene_id: string | null
  aliases: string[]
  introduction?: string
  relationship?: NpcRelationship
  portrait_status?: string
  entry_count: number
  entries?: NpcJournalEntry[]
  has_more?: boolean
  summary?: NpcJournalEntry[]
  overview?: NpcJournalEntry[]
  history_counts?: { general: number; shared: number }
  history_kind?: NpcHistoryKind
  state_visible?: boolean
  insights?: NpcInsights | null
}

export interface LearningProgress {
  phase: 'queued' | 'preparing' | 'extracting' | 'waiting_to_save' | 'saving' | 'recovering' | 'retry_pending' | 'up_to_date'
  elapsed_seconds: number
}

interface NpcJournalController {
  learning: Ref<LearningProgress | null>
  characters: Ref<NpcCard[]>
  details: Ref<NpcCard | null>
  loading: Ref<boolean>
  error: Ref<string>
  pending: Ref<number>
  failed: Ref<number>
  load: (more?: boolean) => Promise<void>
  retryLearning: () => Promise<void>
}

export function useNpcJournal(sessionId: Ref<string>, npcId: Ref<string | undefined>, showState?: Readonly<Ref<boolean>>, history?: Ref<NpcHistoryKind>): NpcJournalController {
  const learning = ref<LearningProgress | null>(null)
  const characters = ref<NpcCard[]>([])
  const details = ref<NpcCard | null>(null)
  const loading = ref(false)
  const error = ref('')
  const pending = ref(0)
  const failed = ref(0)
  let active: AbortController | null = null
  let revision = 0

  function visibleCard(card: NpcCard): NpcCard {
    return showState?.value === false || card.state_visible !== true
      ? { ...card, state_visible: false, insights: null } : card
  }

  async function request(path: string, signal: AbortSignal, method = 'GET'): Promise<unknown> {
    const response = await fetch(`/api/adventures/${encodeURIComponent(sessionId.value)}/${path}`, {
      method, headers: { Authorization: `Bearer ${authState.token}` }, signal,
    })
    if (!response.ok) throw new Error(response.status === 404
      ? 'This character or session is no longer available.' : 'Could not load character information. Please retry.')
    return response.json()
  }

  async function load(more = false): Promise<void> {
    if (!sessionId.value || (more && loading.value)) return
    active?.abort()
    const controller = new AbortController()
    active = controller
    const token = ++revision
    loading.value = true
    error.value = ''
    const timeout = setTimeout(() => controller.abort(), 15000)
    try {
      const offset = more ? details.value?.entries?.length || 0 : 0
      if (npcId.value) {
        const data = await request(`npcs/${encodeURIComponent(npcId.value)}?offset=${offset}${history ? `&history=${history.value}` : ''}`, controller.signal) as NpcCard
        if (token !== revision) return
        details.value = visibleCard({ ...data, entries: more ? [...(details.value?.entries || []), ...(data.entries || [])] : data.entries })
      } else {
        const data = await request('npcs', controller.signal) as { characters: NpcCard[]; pending: number; failed: number; learning?: LearningProgress }
        if (token !== revision) return
        characters.value = data.characters.map(visibleCard)
        pending.value = data.pending
        failed.value = data.failed
        learning.value = data.learning ?? null
      }
    } catch (cause) {
      if (token === revision) error.value = cause instanceof Error && cause.name !== 'AbortError'
        ? cause.message : 'Loading character information timed out. Please retry.'
    } finally {
      clearTimeout(timeout)
      if (token === revision) loading.value = false
    }
  }

  async function retryLearning(): Promise<void> {
    if (loading.value) return
    active?.abort()
    const controller = new AbortController()
    active = controller
    const token = ++revision
    const timeout = setTimeout(() => controller.abort(), 15000)
    loading.value = true
    error.value = ''
    try {
      await request('npc-journal/retry', controller.signal, 'POST')
      if (token !== revision) return
      loading.value = false
      await load()
    } catch {
      if (token === revision) error.value = 'Could not retry character learning. Please try again.'
    } finally {
      clearTimeout(timeout)
      if (token === revision) loading.value = false
    }
  }

  function stop(): void {
    revision++
    active?.abort()
    active = null
    loading.value = false
  }
  watch([sessionId, npcId, () => history?.value], (current, previous) => {
    stop()
    if (current[0] !== previous?.[0] || current[1] !== previous?.[1]) {
      details.value = null
      characters.value = []
      learning.value = null
      pending.value = 0
      failed.value = 0
    } else if (details.value && current[2] !== previous?.[2]) {
      // Keep the profile visible while replacing only this tab's history page.
      details.value = { ...details.value, entries: [], has_more: false, history_kind: history?.value }
    }
    void load()
  }, { immediate: true })
  if (showState) watch(showState, enabled => {
    if (!enabled) {
      if (details.value) details.value = visibleCard(details.value)
      characters.value = characters.value.map(visibleCard)
    } else void load()
  })
  onScopeDispose(stop)
  return { learning, characters, details, loading, error, pending, failed, load, retryLearning }
}
