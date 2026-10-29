import { ref } from 'vue'

export const visualJobProgress = ref<Record<string, string>>({})
const labels: Record<string, string> = {
  analyzing: 'Analyzing the scene…', prompt: 'Preparing the image prompt…',
  submitting: 'Sending to the image provider…', waiting: 'Waiting in ComfyUI queue / generating…',
  downloading: 'Downloading the image…', saving: 'Saving the image…',
}
export function visualStageLabel(stage?: string | null): string | undefined {
  return stage ? labels[stage] : undefined
}
export function updateVisualProgress(id: string, stage?: string | null): void {
  const label = visualStageLabel(stage)
  if (label) visualJobProgress.value = { ...visualJobProgress.value, [id]: label }
  else clearVisualProgress(id)
}
export function clearVisualProgress(id: string): void {
  const next = { ...visualJobProgress.value }
  delete next[id]
  visualJobProgress.value = next
}
