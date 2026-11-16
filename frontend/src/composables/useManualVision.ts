import { computed, onScopeDispose, ref, shallowRef, watch, type Ref } from 'vue'
import { visualService, type VisualKind } from '@/services/visualService'

interface VisualTarget {
  kind: VisualKind
  id: string
  label: string
}

interface ManualVisionOptions {
  adventureId: () => string
  target: Ref<VisualTarget | null>
  open: Ref<boolean>
  prompt: Ref<string>
  advanced: Ref<boolean>
  reference: Ref<boolean>
  controllers?: Ref<Map<string, AbortController>>
  refresh: () => Promise<void>
  notify: (message: string, type: 'success' | 'error' | 'info') => void
}

interface VisualRequest {
  adventureId: string
  target: VisualTarget
  mode: 'image' | 'prompt'
  controller: AbortController
}

/** Only the request belonging to the current dialog may update its draft or busy state. */
export function useManualVision(options: ManualVisionOptions) {
  const active = shallowRef<VisualRequest | null>(null)
  const error = ref('')
  const isRegenerating = computed(() => active.value?.mode === 'image')
  const isSuggestingPrompt = computed(() => active.value?.mode === 'prompt')

  function invalidate() {
    const request = active.value
    request?.controller.abort()
    if (request) finish(request)
    error.value = ''
  }

  watch(() => [options.adventureId(), options.target.value?.kind, options.target.value?.id, options.open.value],
    (current, previous) => {
      invalidate()
      if (current[0] !== previous[0]) options.open.value = false
    }, { flush: 'sync' })
  onScopeDispose(invalidate)

  function start(mode: VisualRequest['mode']): VisualRequest | null {
    if (active.value || !options.open.value || !options.adventureId() || !options.target.value) return null
    const request = { adventureId: options.adventureId(), target: { ...options.target.value },
      mode, controller: new AbortController() }
    error.value = ''
    if (mode === 'image') {
      const key = `${request.target.kind}_${request.target.id}`
      options.controllers?.value.get(key)?.abort()
      options.controllers?.value.set(key, request.controller)
    }
    active.value = request
    return request
  }

  function finish(request: VisualRequest) {
    const key = `${request.target.kind}_${request.target.id}`
    if (options.controllers?.value.get(key) === request.controller) options.controllers.value.delete(key)
    if (active.value === request) active.value = null
  }

  function current(request: VisualRequest) {
    return active.value === request && !request.controller.signal.aborted
  }

  function fail(request: VisualRequest, cause: unknown) {
    if (!current(request)) return
    error.value = cause instanceof Error ? cause.message : 'Visual generation failed. Please retry.'
    options.notify(error.value, 'error')
  }

  async function suggest() {
    const request = start('prompt')
    if (!request) return
    try {
      const suggested = await visualService.suggestPrompt(request.adventureId, request.target.kind,
        request.target.id, options.advanced.value, request.controller.signal)
      if (!current(request)) return
      if (!suggested.trim()) {
        error.value = 'The model returned no usable prompt. Try Suggest Prompt again or keep your manual prompt.'
        options.notify(error.value, 'info')
        return
      }
      options.prompt.value = suggested
      options.notify('AI suggested a prompt based on the description.', 'success')
    } catch (cause) {
      fail(request, cause)
    } finally {
      finish(request)
    }
  }

  async function regenerate() {
    const request = start('image')
    if (!request) return
    let generated = false
    try {
      await visualService.regenerateVisual(request.adventureId, request.target.kind, request.target.id,
        options.prompt.value, options.advanced.value, request.controller.signal, options.reference.value)
      if (!current(request)) return
      generated = true
      await options.refresh()
      if (!current(request)) return
      options.notify(`Visual for ${request.target.label} re-woven.`, 'success')
      options.open.value = false
    } catch (cause) {
      fail(request, generated
        ? new Error('The image was generated, but refreshing the editor failed. Reload the editor to view it.')
        : cause)
    } finally {
      finish(request)
    }
  }

  function cancel() {
    invalidate()
    options.open.value = false
  }

  return { isRegenerating, isSuggestingPrompt, error, regenerate, suggest, cancel }
}
