import { createApp, h, ref } from 'vue'
import '../../src/assets/main.css'
import ManualVisionModal from '../../src/components/editor/ManualVisionModal.vue'
import { useManualVision } from '../../src/composables/useManualVision'
import { visualService } from '../../src/services/visualService'

createApp({
  setup() {
    const target = ref({ kind: 'npc' as const, id: 'ALICE', label: 'Alice', description: 'A physician.', hint: 'Portrait.' })
    const open = ref(true), prompt = ref('My manual prompt.'), advanced = ref(false), reference = ref(false)
    const notices = ref<string[]>([])
    const vision = useManualVision({ adventureId: () => 'adventure', target, open, prompt,
      advanced, reference, refresh: async () => {}, notify: message => notices.value.push(message) })
    return () => h('main', { class: 'min-h-screen bg-slate-950 p-8 text-white' }, [
      h(ManualVisionModal, {
        show: open.value, selectedVisual: target.value, visualPrompt: prompt.value,
        isSuggestingPrompt: vision.isSuggestingPrompt.value, isRegenerating: vision.isRegenerating.value,
        errorMessage: vision.error.value, useAdvancedModel: advanced.value, useCurrentImage: reference.value,
        uploadLimits: visualService.UPLOAD_LIMITS, formatBytes: String, fixNewlines: (value: string) => value,
        onClose: vision.cancel, onCancelRegen: vision.cancel, onSuggest: vision.suggest, onRegenerate: vision.regenerate,
        'onUpdate:visualPrompt': (value: string) => { prompt.value = value },
        'onUpdate:useAdvancedModel': (value: boolean) => { advanced.value = value },
        'onUpdate:useCurrentImage': (value: boolean) => { reference.value = value },
      }),
      h('button', { onClick: () => {
        target.value = { ...target.value, id: 'BEATRICE', label: 'Beatrice' }
        prompt.value = 'My Beatrice prompt.'
        open.value = true
      } }, 'Edit Beatrice'),
      h('output', { id: 'notices' }, notices.value.join('\n')),
    ])
  },
}).mount('#app')
