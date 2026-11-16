/** Real time spent viewing a session, independent of its story clock. */
export function formatPlaytime(seconds = 0): string {
  const total = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0
  if (total === 0) return '0 min'
  if (total < 60) return '<1 min'
  const minutes = Math.floor(total / 60)
  if (minutes < 60) return `${minutes} min`
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`
}
