import { createApp, h, ref } from 'vue'
import '../../src/assets/main.css'
import VisualsSection from '../../src/components/admin/VisualsSection.vue'
import { testService } from '../../src/services/testService'
import { clonePresetData } from '../../src/services/comfyPresetDraft'
import type { ComfyOptions, ComfyTestOptions } from '../../src/types/comfyui'

createApp({
  setup() {
    const options = ref<ComfyOptions>({
      comfyui_url: 'https://comfy.test', comfyui_timeout: 600, comfyui_profiles: {},
      comfyui_presets: { nova: {
        name: 'Nova Anima', auto_prompt_template: false, reference: null,
        prompt_rules: { template_id: 'custom', format: 'description', language: 'English', max_words: 100,
          adapt_with_llm: true, prefix: 'masterpiece', suffix: '', negative_prompt: 'text', instructions: '' },
        generate: { name: 'Nova workflow', graph: {
          model: { class_type: 'UNETLoader', inputs: { unet_name: 'novaAnimeAM_v10.safetensors' } },
          text: { class_type: 'CLIPTextEncode', inputs: { text: '' } },
          save: { class_type: 'SaveImage', inputs: { images: ['text', 0] } },
        }, bindings: { prompt: { node_id: 'text', input_name: 'text' } }, output_node: 'save' },
      } }, comfyui_assignments: { background: 'nova' },
    })
    const installed = clonePresetData(options.value.comfyui_presets!.nova!.generate!)
    installed.name = 'Installed Nova workflow'
    installed.graph.model!.inputs.unet_name = 'installed-nova.safetensors'
    options.value.comfyui_workflows = { installed: { revision: 1, workflow: installed } }
    const saved = ref('')
    function test(value: ComfyTestOptions & { key: string }) {
      void testService.testVision(value.key, '', 'comfyui', '', undefined,
        undefined, undefined, undefined, undefined, undefined, undefined, undefined, value)
    }
    return () => h('main', { class: 'min-h-screen bg-slate-950 text-white' }, [
      h(VisualsSection, {
        t2iForm: { ...options.value, simple_model_provider: 'comfyui', advanced_model_provider: 'comfyui',
          simple_model: '', advanced_model: '', image_format: 'png', scene_model_quality: 'advanced' },
        availableConstants: { image_providers: [{ id: 'comfyui', name: 'ComfyUI' }], predefined_image_models: {} },
        configuredKeys: {}, isSubmitting: false, testResults: testService.testResults.value,
        onTest: test,
        onSave: (value: ComfyOptions) => { saved.value = JSON.stringify(value); options.value = value },
      }),
      h('pre', { id: 'saved' }, saved.value),
    ])
  },
}).mount('#app')
