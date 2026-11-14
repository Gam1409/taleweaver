import type { EquipmentCondition } from './equipmentSlots'

export function conditionSnapshot(rows: EquipmentCondition[]) {
  const ordered = [...rows].sort((a, b) => (b.updated_revision ?? -1) - (a.updated_revision ?? -1))
  const latest = ordered.find(row => Number.isSafeInteger(row.updated_revision) && row.updated_revision! >= 0)
  if (!latest) return { current: rows, retained: [] as EquipmentCondition[] }
  const sameSource = (row: EquipmentCondition) => latest.observed_message_id
    ? row.observed_message_id === latest.observed_message_id
    : row.updated_revision === latest.updated_revision
  return { current: ordered.filter(sameSource), retained: ordered.filter(row => !sameSource(row)) }
}

export function conditionAge(row: EquipmentCondition, gameMinute?: number) {
  if (row.last_changed_minute == null || gameMinute == null) return ''
  const age = Math.max(0, gameMinute - row.last_changed_minute)
  return age === 0 ? 'Changed this game minute' : `Changed ${age} game min ago`
}

export function conditionKind(row: EquipmentCondition) {
  const labels: Record<string, string> = { injury: 'Injury', contamination: 'Contamination', fluid: 'Fluid', pain: 'Pain', other: 'Physical condition', item_state: 'Item state' }
  return row.kind ? labels[row.kind] ?? 'Physical condition' : ''
}
