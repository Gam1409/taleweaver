import { createApp, h, ref, type Component } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import '../../src/assets/main.css'
import 'rpg-awesome/css/rpg-awesome.min.css'
import { useWorkspaceTheme } from '../../src/composables/useWorkspaceTheme'
import { configState } from '../../src/store/config'
import { authState } from '../../src/store/auth'
import { createPortalFixture } from './portalFixture'
import DeleteAdventureModal from '../../src/components/portal/DeleteAdventureModal.vue'
import DeleteAllAdventuresModal from '../../src/components/portal/DeleteAllAdventuresModal.vue'
import ImportExamplesModal from '../../src/components/portal/ImportExamplesModal.vue'
import ImportWarningModal from '../../src/components/portal/ImportWarningModal.vue'
import DeleteSessionModal from '../../src/components/portal/DeleteSessionModal.vue'
import DeleteAllSessionsModal from '../../src/components/portal/DeleteAllSessionsModal.vue'
import SessionNoteModal from '../../src/components/portal/SessionNoteModal.vue'
import AboutModal from '../../src/components/portal/AboutModal.vue'
import ImportConflictModal from '../../src/components/portal/ImportConflictModal.vue'
import SetupWarningModal from '../../src/components/portal/SetupWarningModal.vue'
import CloneProgressModal from '../../src/components/portal/CloneProgressModal.vue'
import ExportProgressModal from '../../src/components/portal/ExportProgressModal.vue'
import GenerationProgressModal from '../../src/components/portal/GenerationProgressModal.vue'
import MigrateAdventureModal from '../../src/components/portal/MigrateAdventureModal.vue'
import UserEditModal from '../../src/components/admin/UserEditModal.vue'
import CatalogEditModal from '../../src/components/admin/CatalogEditModal.vue'
import PromptInputModal from '../../src/components/admin/PromptInputModal.vue'
import MemoryIndexActions from '../../src/components/portal/MemoryIndexActions.vue'
import LicensesModal from '../../src/components/portal/LicensesModal.vue'
import ChangeCredentialsModal from '../../src/components/portal/ChangeCredentialsModal.vue'
import ComfyWorkflowSlot from '../../src/components/admin/ComfyWorkflowSlot.vue'
import ComfyPurposeAssignments from '../../src/components/admin/ComfyPurposeAssignments.vue'
import ComfyPresetModal from '../../src/components/admin/ComfyPresetModal.vue'

const fixture = createPortalFixture()
const originalFetch = window.fetch.bind(window)
window.fetch = async (input, options) => {
  const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
  const url = new URL(raw, location.origin)
  if (!url.pathname.startsWith('/api/')) return originalFetch(input, options)
  const path = url.pathname.slice(4)
  if (path.endsWith('/status')) return Response.json({ is_ready: true, status: 'Completed', completed_stages: 5 })
  if (path.endsWith('/generation-logs')) return Response.json({ logs: [{ timestamp: '2026-01-01T12:00:00Z', type: 'status', content: 'The fictional adventure is ready.' }] })
  if (path === '/settings/comfyui/prompt-templates') return Response.json([])
  if (path === '/settings/comfyui/starter-workflows') return Response.json([{ id: 'sdxl', name: 'Illustration workflow', generate: workflow, reference: workflow }])
  if (path === '/settings/comfyui/starter-presets') return Response.json([])
  if (path === '/settings/comfyui/detect-template') return Response.json({ template_id: null, models: [], message: 'Fictional workflow catalog.' })
  const body = typeof options?.body === 'string' ? JSON.parse(options.body) : undefined
  return fixture.respond(path, options?.method || 'GET', body)
}
const events: string[] = []
Object.assign(window, { workspaceWindows: { ...fixture, events } })
Object.assign(authState, { user: fixture.user, token: 'fictional-preview', isAuthenticated: true, isInitialized: true })
Object.assign(configState, { appVersion: '0.7.1-beta', isLoaded: true })
const title = 'Letters from the Coast'
const catalogItem = { id: 'watercolour', name: 'Watercolour', description: 'Soft edges and painted light.', instruction: '', image_url: null }
const workflow = { name: 'Coastal illustration', graph: { '1': { class_type: 'CLIPTextEncode', inputs: { text: 'A quiet coastal archive.' } }, '2': { class_type: 'SaveImage', inputs: { images: ['1', 0] } } }, bindings: { prompt: { node_id: '1', input_name: 'text' } }, output_node: '2' }
const options = { comfyui_url: '', comfyui_timeout: 120, comfyui_profiles: {}, comfyui_presets: { coastal: { name: 'Coastal illustration', generate: workflow, reference: null, prompt_rules: null, auto_prompt_template: true } }, comfyui_assignments: { simple: 'coastal' } }
const windows: Record<string, { component: Component; props: Record<string, unknown> }> = {
  'delete-adventure': { component: DeleteAdventureModal, props: { adventureTitle: title } },
  'delete-adventures': { component: DeleteAllAdventuresModal, props: { adventureCount: 3 } },
  'import-examples': { component: ImportExamplesModal, props: {} },
  'import-warning': { component: ImportWarningModal, props: { type: 'samples', conflicts: [{ title, already_exists: true }], isImporting: false } },
  'delete-session': { component: DeleteSessionModal, props: { sessionTitle: title } },
  'delete-sessions': { component: DeleteAllSessionsModal, props: { sessionCount: 2 } },
  'session-note': { component: SessionNoteModal, props: { initialNote: 'Ask Mira about the lighthouse.' } },
  about: { component: AboutModal, props: { isOpen: true } },
  'import-conflict': { component: ImportConflictModal, props: { conflict: { title, template_id: 'coast', existing_version: '1.1', new_version: '1.2' } } },
  setup: { component: SetupWarningModal, props: { isOpen: true } },
  clone: { component: CloneProgressModal, props: { sessionTitle: title, progress: 100, stage: 'completed' } },
  export: { component: ExportProgressModal, props: { adventureTitle: title, format: 'adz', progress: 100 } },
  generation: { component: GenerationProgressModal, props: { adventureTitle: title, adventureId: 'coast' } },
  migrate: { component: MigrateAdventureModal, props: { isOpen: true, template: { title, template_id: 'coast', is_legacy_format: true } } },
  user: { component: UserEditModal, props: { isOpen: true, isEditingExisting: false, user: { username: 'Storykeeper', role: 'user', bio: '' }, isSubmitting: false } },
  catalog: { component: CatalogEditModal, props: { isOpen: true, isEditingExisting: true, item: catalogItem, index: 0, type: 'styles' } },
  prompt: { component: PromptInputModal, props: { isOpen: true, data: { type: 'styles', item: catalogItem, index: 0 } } },
  memory: { component: MemoryIndexActions, props: { templateId: 'coast', title } },
  licenses: { component: LicensesModal, props: {} },
  credentials: { component: ChangeCredentialsModal, props: { isOpen: true } },
  workflow: { component: ComfyWorkflowSlot, props: { modelValue: workflow, library: {}, url: '' } },
  assignments: { component: ComfyPurposeAssignments, props: { modelValue: options, settings: {}, testResults: {} } },
  presets: { component: ComfyPresetModal, props: { open: true, modelValue: options, profile: 'simple' } },
}
const selected = new URLSearchParams(location.search).get('window') || 'delete-adventure'
const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { render: () => h('p', 'Window validation') } }, { path: '/admin', component: { render: () => h('p', 'Administration') } }] })
await router.push('/')
createApp({ setup() {
  useWorkspaceTheme()
  const open = ref(true)
  const current = windows[selected]
  const close = () => { events.push('close'); open.value = false }
  return () => h('main', { class: 'workspace-view min-h-dvh p-4 text-slate-200' }, [
    h('p', { class: 'mb-4 text-sm text-slate-400' }, 'Window validation · fictional data'),
    current && open.value ? h(current.component, { ...current.props, onClose: close, onConfirm: () => events.push('confirm'), onSave: () => events.push('save') }) : h('p', 'Closed'),
  ])
} }).use(router).mount('#app')
