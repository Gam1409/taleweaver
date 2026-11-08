import { createApp, h } from 'vue'
import { createRouter, createMemoryHistory, RouterView } from 'vue-router'
import '../../src/assets/main.css'
import AdventureEditorView from '../../src/views/AdventureEditorView.vue'

const router = createRouter({ history: createMemoryHistory(), routes: [
  { path: '/', name: 'adventure-editor', component: AdventureEditorView, props: { adventureId: 'scroll-adventure' } },
] })
await router.push('/')
await router.isReady()
createApp({
  render: () => h('div', { class: 'h-app flex flex-col overflow-hidden' }, [
    h('header', { class: 'h-24 shrink-0 bg-slate-900 p-6 text-white' }, 'TaleWeaver header'),
    h('main', { id: 'route-viewport', class: 'flex-1 min-h-0 overflow-hidden' }, [h(RouterView)]),
  ]),
}).use(router).mount('#app')
