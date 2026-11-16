/** Connection permissions never imply that dependent workflow stages can overlap. */
import { LLM_ROLES, type LLMRole } from './llmRoleEndpoints'

export interface ParallelPolicy {
  enabled: boolean
  max_concurrent: number
}
export interface ParallelSettings {
  roles: Partial<Record<LLMRole, ParallelPolicy>>
}

export function normalizeParallel(value?: ParallelSettings | null): ParallelSettings {
  return {
    roles: Object.fromEntries(
      Object.entries(value?.roles ?? {}).map(([role, policy]) => [role, { ...policy }])
    )
  }
}

export function roleParallel(value: ParallelSettings, role: LLMRole): ParallelPolicy {
  return { enabled: false, max_concurrent: 2, ...value.roles[role] }
}

/** Saving the visible controls must also apply their unchecked defaults. */
export function parallelForSave(value: ParallelSettings): ParallelSettings {
  return {
    roles: Object.fromEntries(LLM_ROLES.map(role => [role, roleParallel(value, role)]))
  }
}

export function updateParallel(
  value: ParallelSettings,
  role: LLMRole,
  change: Partial<ParallelPolicy>
): ParallelSettings {
  const next = normalizeParallel(value)
  next.roles[role] = { ...roleParallel(value, role), ...change }
  return next
}
