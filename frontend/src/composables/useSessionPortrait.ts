import { onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { runVisualJob } from '@/services/visualJobs'

export interface PortraitNpc {
  id?: string
  name?: string
  description?: string
  image_url?: string | null
  entity_type?: string
}

export interface PortraitTarget extends PortraitNpc {
  id: string
  name: string
}

export function useSessionPortrait(
  sessionId: Ref<string>,
  entities: Ref<PortraitNpc[]>,
  metadata: Ref<Record<string, PortraitNpc>>
): {
  portraitTarget: Ref<PortraitTarget | null>
  portraitBusy: Ref<boolean>
  portraitError: Ref<string>
  portraitUpdated: Ref<boolean>
  openPortrait: (npc: PortraitTarget) => void
  closePortrait: () => void
  regeneratePortrait: () => Promise<void>
} {
  const portraitTarget = ref<PortraitTarget | null>(null)
  const portraitBusy = ref(false)
  const portraitError = ref('')
  const portraitUpdated = ref(false)
  let controller: AbortController | null = null

  function openPortrait(npc: PortraitTarget): void {
    if (npc.id === 'PLAYER' || portraitBusy.value) return
    portraitTarget.value = { ...npc }
    portraitError.value = ''
    portraitUpdated.value = false
  }

  function closePortrait(): void {
    controller?.abort()
    portraitTarget.value = null
  }

  async function regeneratePortrait(): Promise<void> {
    const target = portraitTarget.value
    if (!target || portraitBusy.value) return
    const gameId = sessionId.value
    const request = new AbortController()
    controller = request
    portraitBusy.value = true
    portraitError.value = ''
    portraitUpdated.value = false
    try {
      const result = await runVisualJob(
        'session_npc',
        { target_id: target.id },
        undefined,
        request.signal,
        gameId
      )
      if (request.signal.aborted || sessionId.value !== gameId) return
      if (typeof result.image_url !== 'string' || !result.image_url)
        throw new Error('No portrait was returned.')
      const imageUrl = result.image_url
      entities.value = entities.value.map(npc =>
        npc.id === target.id ? { ...npc, image_url: imageUrl } : npc
      )
      metadata.value = Object.fromEntries(
        Object.entries(metadata.value).map(([key, npc]) => [
          key,
          key === target.id || npc.id === target.id ? { ...npc, image_url: imageUrl } : npc
        ])
      )
      portraitTarget.value = { ...target, image_url: imageUrl }
      portraitUpdated.value = true
    } catch (error) {
      if (!request.signal.aborted)
        portraitError.value =
          error instanceof Error
            ? error.message
            : 'Portrait generation failed. The previous image was kept.'
    } finally {
      portraitBusy.value = false
      controller = null
    }
  }

  watch(sessionId, closePortrait)
  onBeforeUnmount(closePortrait)
  return {
    portraitTarget,
    portraitBusy,
    portraitError,
    portraitUpdated,
    openPortrait,
    closePortrait,
    regeneratePortrait
  }
}
