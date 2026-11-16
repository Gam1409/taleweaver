import { apiFetch } from '@/services/http'

export interface PublicationReport {
  warnings: string[]
  requires_acknowledgement: boolean
  compatible: boolean
  source_mode: string
  target_mode: string
}

const path = (id: string) => `/adventures/templates/${encodeURIComponent(id)}/publication`

export const adventurePublicationService = {
  async preview(id: string): Promise<PublicationReport> {
    const response = await apiFetch(`${path(id)}/preview`, { timeoutMs: 60000 })
    if (!response.ok) {
      const body = response.status === 422 ? await response.json().catch(() => null) : null
      const reason = typeof body?.detail === 'string' ? body.detail.slice(0, 2000) : null
      throw new Error(reason || 'Could not check export compatibility. Please retry.')
    }
    return response.json()
  },
  async export(id: string, acknowledge: boolean): Promise<Blob> {
    const response = await apiFetch(`${path(id)}/export`, {
      method: 'POST',
      includeJson: true,
      timeoutMs: 120000,
      body: JSON.stringify({ acknowledge_changes: acknowledge })
    })
    if (!response.ok)
      throw new Error(
        response.status === 409
          ? 'The adventure or compatibility report changed. Check compatibility again before exporting.'
          : 'Could not prepare the compatible copy. Your original adventure is unchanged.'
      )
    return response.blob()
  }
}
