import { createApp, h, ref } from 'vue'
import '../../src/assets/main.css'
import ComfyPresetStarter from '../../src/components/admin/ComfyPresetStarter.vue'
import type { ComfyPreset } from '../../src/types/comfyui'

createApp({
  setup() {
    const created = ref<ComfyPreset[]>([])
    const url = ref('http://comfy-one.test:8188')
    return () => h('main', { class: 'min-h-screen bg-slate-950 p-8 text-white' }, [
      h('h1', { class: 'mb-6 text-xl font-bold' }, 'ComfyUI task presets'),
      h('label', ['ComfyUI URL', h('input', { value: url.value, 'aria-label': 'ComfyUI URL',
        class: 'mb-5 block w-full rounded border border-slate-700 bg-slate-900 p-2',
        onInput: (event: Event) => { url.value = (event.target as HTMLInputElement).value } })]),
      h(ComfyPresetStarter, { url: url.value, purpose: 'npc', onCreate: (preset: ComfyPreset) => created.value.push(preset) }),
      h('output', { id: 'created' }, JSON.stringify(created.value)),
    ])
  },
}).mount('#app')
