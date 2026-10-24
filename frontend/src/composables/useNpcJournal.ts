import { onScopeDispose, ref, watch, type Ref } from 'vue'
import { authState } from '@/store/auth'

export interface NpcJournalEntry {
  id: string
  category: string
  topic?: string
  text: string
  evidence: string
  source: 'observed' | 'claimed'
  scene_id?: string
  recorded_at?: string
}

export interface NpcCard {
  id: string
  name: string
  description: string
  image_url: string | null
  scene_id: string | null
  aliases: string[]
  introduction?: string
  inventory: Array<string | { id?: string; name?: string; quantity?: number }>
  portrait_status?: string
  entry_count: number
  entries?: NpcJournalEntry[]
  has_more?: boolean
}

interface NpcJournalController {
  characters: Ref<NpcCard[]>
  details: Ref<NpcCard | null>
  loading: Ref<boolean>
  error: Ref<string>
  pending: Ref<number>
  failed: Ref<number>
  load: (more?: boolean) => Promise<void>
  retryLearning: () => Promise<void>
}

export function useNpcJournal(sessionId: Ref<string>, npcId: Ref<string | undefined>): NpcJournalController {
  const characters = ref<NpcCard[]>([])
  const details = ref<NpcCard | null>(null)
  const loading = ref(false)
  const error = ref('')
  const pending = ref(0)
  const failed = ref(0)
  let active: AbortController | null = null
  let revision = 0

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
        const data = await request(`npcs/${encodeURIComponent(npcId.value)}?offset=${offset}`, controller.signal) as NpcCard
        if (token !== revision) return
        details.value = { ...data, entries: more ? [...(details.value?.entries || []), ...(data.entries || [])] : data.entries }
      } else {
        const data = await request('npcs', controller.signal) as { characters: NpcCard[]; pending: number; failed: number }
        if (token !== revision) return
        characters.value = data.characters
        pending.value = data.pending
        failed.value = data.failed
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
  watch([sessionId, npcId], () => { stop(); details.value = null; characters.value = []; void load() }, { immediate: true })
  onScopeDispose(stop)
  return { characters, details, loading, error, pending, failed, load, retryLearning }
}
