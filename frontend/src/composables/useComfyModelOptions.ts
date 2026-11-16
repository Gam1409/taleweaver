import { onBeforeUnmount, ref, watch } from 'vue'
import { comfyRequest } from '@/services/comfyPresetService'
import type { ComfyWorkflow } from '@/types/comfyui'

type ModelOption = { node_id: string; input_name: string; choices: string[] }

export function useComfyModelOptions(
  props: { url: string; modelValue: ComfyWorkflow },
  busy: (value: boolean) => void
) {
  const options = ref<ModelOption[]>([])
  let version = 0
  watch(
    () =>
      JSON.stringify([
        props.url,
        Object.entries(props.modelValue.graph).map(([id, node]) => [
          id,
          node.class_type,
          Object.keys(node.inputs)
        ])
      ]),
    async () => {
      const current = ++version
      options.value = []
      if (!props.url) {
        busy(false)
        return
      }
      busy(true)
      try {
        const result = await comfyRequest<ModelOption[]>('model-options', {
          url: props.url,
          workflow: props.modelValue
        })
        if (current === version) options.value = result
      } catch {
        if (current === version) options.value = []
      } finally {
        if (current === version) busy(false)
      }
    },
    { immediate: true, flush: 'sync' }
  )
  onBeforeUnmount(() => {
    version++
    busy(false)
  })
  function choicesFor(nodeId: string, field: string): string[] | undefined {
    return options.value.find(item => item.node_id === nodeId && item.input_name === field)?.choices
  }
  return { choicesFor }
}
