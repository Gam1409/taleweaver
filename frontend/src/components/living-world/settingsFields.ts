import type { LivingWorldPreferences } from '@/services/livingWorld'

export const concordiaDefaults = (): LivingWorldPreferences => ({
  living_world_enabled: false, deliberation_enabled: false, decision_engine: 'concordia',
  dialogue_choices_enabled: true,
  live_enabled: true, live_interval_seconds: 60, allow_concurrent_requests: false,
  mode: 'PAUSE', offline_time_scale: 1, max_catchup_game_hours: 6, max_events: 16,
  max_wall_seconds: 2, auto_catchup_on_resume: false, auto_schedule: true,
  schedule_interval_minutes: 60, max_npcs: 4, max_decisions_per_run: 1,
  max_deliberations: 8, decision_max_tokens: 256,
})

type NumericKey = 'offline_time_scale' | 'max_catchup_game_hours' | 'max_events' | 'max_wall_seconds' | 'schedule_interval_minutes' | 'max_npcs' | 'max_decisions_per_run' | 'max_deliberations' | 'decision_max_tokens'
interface SliderField { key: NumericKey; label: string; help: string; min: number; max: number; step: number; unit?: string }
export const groups: { title: string; fields: SliderField[] }[] = [
  { title: 'Time & catch-up', fields: [
    { key: 'offline_time_scale', label: 'Offline time scale', help: 'Game hours added for each real hour away in Catch up mode. Zero adds no offline time. Pause mode ignores this setting.', min: 0, max: 24, step: 0.1, unit: '×' },
    { key: 'max_catchup_game_hours', label: 'Game time per batch', help: 'Maximum game hours processed by one batch. Any unfinished offline time stays queued for the next batch.', min: 0, max: 72, step: 0.5, unit: 'h' },
  ] },
  { title: 'NPC routines', fields: [
    { key: 'schedule_interval_minutes', label: 'Routine interval', help: 'Game minutes between recurring decisions. Applies when recurring routines are enabled. A shorter interval creates more decision opportunities, not faster model responses.', min: 15, max: 1440, step: 15, unit: 'min' },
    { key: 'max_npcs', label: 'NPCs per routine', help: 'Maximum NPCs selected for a routine. The selected group rotates so the same characters do not always go first.', min: 1, max: 8, step: 1 },
  ] },
  { title: 'Request & processing limits', fields: [
    { key: 'max_decisions_per_run', label: 'Requests per batch', help: 'Maximum model decision attempts in one manual or return-triggered batch. Each Concordia step makes at most one Utility model request.', min: 1, max: 4, step: 1 },
    { key: 'max_deliberations', label: 'Timeline request allowance', help: 'Total decision attempts allowed in one session timeline. Failed and stopped attempts also count. This is not a daily allowance and does not reset on each batch. Zero prevents decisions.', min: 0, max: 128, step: 1 },
    { key: 'decision_max_tokens', label: 'Response token limit', help: 'Requested output token cap for one decision, further limited by the Utility model setting. It does not measure billing or cap input tokens. Too small a value may truncate the JSON response.', min: 128, max: 1024, step: 32, unit: 'tokens' },
    { key: 'max_events', label: 'Events per batch', help: 'Shared maximum for rule events and model decisions across one batch. Zero pauses processing without deleting the backlog.', min: 0, max: 128, step: 1 },
    { key: 'max_wall_seconds', label: 'Rules processing budget', help: 'Wall-clock seconds allowed for local rules work across one batch. This is NOT the LLM timeout: model requests use the Utility model timeout, including queue waiting.', min: 0, max: 10, step: 0.5, unit: 's' },
  ] },
]
