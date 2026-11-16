import { createApp, h, nextTick, ref } from 'vue'
import '../../src/assets/main.css'
import SystemDiagnosticsSection from '../../src/components/admin/SystemDiagnosticsSection.vue'
import type { SystemDiagnosticsSettings } from '../../src/services/systemDiagnosticsService'

let stored: SystemDiagnosticsSettings = { enabled: true, detailed_logging: false, log_directory: 'log', retention_files: 5 }
let loadFailure = false, saveFailure = false, pending: Promise<void> | null = null, release: (() => void) | null = null
const writes: { enabled: boolean; detailed_logging?: boolean; state_failure_traces?: boolean }[] = []
const revision = ref(0), originalFetch = window.fetch.bind(window)
window.fetch = async (input, options) => {
  const path = String(input)
  if (!path.includes('/api/')) return originalFetch(input, options)
  if (!path.endsWith('/system-diagnostics')) return Response.json({}, { status: 501 })
  if (!options?.method || options.method === 'GET') return loadFailure ? Response.json({}, { status: 503 }) : Response.json(stored)
  const body = JSON.parse(String(options.body))
  writes.push(body)
  if (pending) await pending
  if (saveFailure) return Response.json({ detail: 'Storage unavailable' }, { status: 503 })
  stored = { ...stored, ...body, detailed_logging: body.enabled && body.detailed_logging, state_failure_traces: body.enabled && body.state_failure_traces }
  return Response.json(stored)
}
Object.assign(window, { diagnosticsFixture: {
  writes,
  setLoadFailure(value: boolean) { loadFailure = value },
  setSaveFailure(value: boolean) { saveFailure = value },
  holdSave() { pending = new Promise(resolve => { release = resolve }) },
  releaseSave() { release?.(); pending = null },
  async remount() { revision.value++; await nextTick() },
} })
createApp({ render: () => h('main', { class: 'min-h-dvh bg-slate-950 p-4 text-slate-100 md:p-8' }, [
  h('div', { class: 'mx-auto max-w-5xl' }, h(SystemDiagnosticsSection, { key: revision.value })),
]) }).mount('#app')
