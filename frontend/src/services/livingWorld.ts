import { apiFetch } from './http'

export interface LivingWorldPreferences {
  living_world_enabled: boolean
  mode: 'PAUSE' | 'CATCH_UP'
  offline_time_scale: number
  max_catchup_game_hours: number
  max_events: number
  max_wall_seconds: number
  dialogue_choices_enabled?: boolean
  live_enabled?: boolean
  live_interval_seconds?: number
  allow_concurrent_requests?: boolean
  auto_catchup_on_resume: boolean
  deliberation_enabled: boolean
  decision_engine: 'native' | 'concordia'
  auto_schedule: boolean
  schedule_interval_minutes: number
  max_npcs: number
  max_decisions_per_run: number
  max_deliberations: number
  decision_max_tokens: number
}

export interface LivingWorldStatus {
  settings: LivingWorldPreferences
  revision: number
  status: string
  cursor: number
  target: number
  pending_events: number
  last_run_events: number
  llm_calls: number
  concordia_available?: boolean
  decision_running?: boolean
  live_running?: boolean
  live_paused?: boolean
  live_error?: string
  recap: string[]
}

export function createPresenceId(): string {
  // getRandomValues also works on HTTP LAN origins where randomUUID is unavailable.
  return Array.from(crypto.getRandomValues(new Uint32Array(4)), value => value.toString(16).padStart(8, '0')).join('-')
}

export async function livingWorldRequest<T>(id: string, suffix = '', method = 'GET', payload?: unknown): Promise<T> {
  const response = await apiFetch(`/adventures/${encodeURIComponent(id)}/living-world${suffix}`, {
    method, timeoutMs: ['/cycle', '/deliberate'].includes(suffix) ? null : 30_000, keepalive: suffix === '/presence',
    ...(payload === undefined ? {} : { includeJson: true, body: JSON.stringify(payload) }),
  })
  const result = await response.json()
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not update Living World.')
  return result as T
}
