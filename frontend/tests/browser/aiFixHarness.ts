import { createApp, h, ref } from 'vue'
import '../../src/assets/main.css'
import ValidationTab from '../../src/components/editor/ValidationTab.vue'
import { setToken } from '../../src/store/auth'

const response = await fetch('/api/ai-fix-fixture/bootstrap')
const fixture = await response.json()
setToken(fixture.token)

createApp({
  setup() {
    const notifications = ref<string[]>([])
    const applied = ref(0)
    return () => h('main', { class: 'min-h-screen bg-slate-950 p-6 text-slate-100' }, [
      h(ValidationTab, {
        templateId: fixture.template_id,
        onNotify: (message: string) => notifications.value.push(message),
        onFixApplied: () => { applied.value += 1 },
      }),
      h('output', { id: 'applied-count' }, String(applied.value)),
      h('output', { id: 'notifications' }, notifications.value.join('\n')),
    ])
  },
}).mount('#app')
