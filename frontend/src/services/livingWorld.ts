import { apiFetch } from './http'

export interface LivingWorldPreferences {
  living_world_enabled: boolean
  mode: 'PAUSE' | 'CATCH_UP'
  offline_time_scale: number
  max_catchup_game_hours: number
  max_events: number
  max_wall_seconds: number
  auto_catchup_on_resume: boolean
}

export interface LivingWorldStatus {
  settings: LivingWorldPreferences
  revision: number
  status: string
  cursor: number
  target: number
  pending_events: number
  last_run_events: number
  recap: string[]
}

export function createPresenceId(): string {
  // getRandomValues also works on HTTP LAN origins where randomUUID is unavailable.
  return Array.from(crypto.getRandomValues(new Uint32Array(4)), value => value.toString(16).padStart(8, '0')).join('-')
}

export async function livingWorldRequest<T>(id: string, suffix = '', method = 'GET', payload?: unknown): Promise<T> {
  const response = await apiFetch(`/adventures/${encodeURIComponent(id)}/living-world${suffix}`, {
    method, timeoutMs: 30_000, keepalive: suffix === '/presence',
    ...(payload === undefined ? {} : { includeJson: true, body: JSON.stringify(payload) }),
  })
  const result = await response.json()
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not update Living World.')
  return result as T
}
