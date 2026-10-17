import { API_BASE, authHeaders } from '@/services/http'
import type { SpecialAttack } from '@/types'

export type SpecialAttackOwner = 'protagonist' | 'npc'

function formatError(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : String(d)))
      .join('; ')
  }
  return 'Failed to save special attacks'
}

export const specialAttackService = {
  async save(
    adventureId: string,
    targetType: SpecialAttackOwner,
    targetId: string,
    specialActions: SpecialAttack[],
  ): Promise<SpecialAttack[]> {
    const res = await fetch(`${API_BASE}/adventures/${adventureId}/editor/special-actions`, {
      method: 'PUT',
      headers: authHeaders(true),
      body: JSON.stringify({ target_type: targetType, target_id: targetId, special_actions: specialActions }),
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      throw new Error(formatError(data?.detail))
    }
    return (data.special_actions ?? []) as SpecialAttack[]
  },
}
