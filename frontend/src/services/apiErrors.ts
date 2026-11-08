/** Read public error messages without stringifying objects or exposing validation inputs. */
function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim().slice(0, 2000) : ''
}

function describe(value: unknown, depth = 0): string {
  if (depth > 3) return ''
  if (typeof value === 'string') return text(value)
  if (Array.isArray(value)) {
    return value.slice(0, 5).map(entry => describe(entry, depth + 1)).filter(Boolean).join('; ')
  }
  const data = record(value)
  if (!data) return ''
  const message = text(data.msg) || text(data.message)
  if (!message) return describe(data.detail, depth + 1)
  const path = Array.isArray(data.loc) ? data.loc
    .filter((part, index) => !(index === 0 && typeof part === 'string' && ['body', 'query', 'path'].includes(part)))
    .filter(part => typeof part === 'string' || typeof part === 'number').join('.') : ''
  return path ? `${path}: ${message}` : message
}

export function apiErrorMessage(payload: unknown, fallback: string, status?: number): string {
  const data = record(payload)
  const detail = describe(data?.detail ?? data?.message ?? payload)
  const prefix = typeof status === 'number' && status >= 100 && status <= 599
    ? `${fallback} (HTTP ${status})` : fallback
  return detail ? `${prefix}: ${detail}` : prefix
}

export async function responseError(response: Response, fallback: string): Promise<Error> {
  const data: unknown = await response.json().catch(() => null)
  return new Error(apiErrorMessage(data, fallback, response.status))
}
