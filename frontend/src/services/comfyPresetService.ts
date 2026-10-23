import { apiFetch } from '@/services/http'
import type { PromptTemplate } from '@/types/comfyui'

export async function comfyRequest<T>(path: string, body?: unknown): Promise<T> {
  const response = await apiFetch(`/settings/comfyui/${path}`, body === undefined ? {} : {
    method: 'POST', includeJson: true, body: JSON.stringify(body), timeoutMs: 120000,
  })
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Check the preset and workflow inputs.')
  return data as T
}

let templates: Promise<PromptTemplate[]> | undefined
export function loadPromptTemplates(): Promise<PromptTemplate[]> {
  templates ??= comfyRequest<PromptTemplate[]>('prompt-templates').catch(error => {
    templates = undefined
    throw error
  })
  return templates
}
