import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, createSSRApp, effectScope, h, nextTick, ref } from 'vue'
import { renderToString } from '@vue/server-renderer'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const source = path => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8')
const tick = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)) }
function evaluate(code, dependencies = {}) {
  const module = { exports: {} }
  const compiled = ts.transpileModule(code, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  new Function('require', 'module', 'exports', compiled)(name => dependencies[name] ?? require(name), module, module.exports)
  return module.exports
}
const load = (path, dependencies) => evaluate(source(path), dependencies)
function component(path, dependencies = {}, expose = '') {
  const text = source(path).replace('</script>', `${expose}\n</script>`)
  const { descriptor } = parse(text)
  return evaluate(compileScript(descriptor, { id: path, inlineTemplate: !expose }).content, dependencies).default
}
const preferences = () => ({
  mode: 'live', actor_ids: ['NPC_雪'], max_active_npcs: 3, model_role: 'complex',
  max_output_tokens: 1200, max_input_chars: 24000, max_calls_per_turn: 25,
  memory_limit: 12, semantic_memory: true, npc_concurrency: 2, failure_policy: 'strict',
})
const status = (settings = preferences(), revision = 4) => ({
  settings, revision, available: true, characters: [{ id: 'NPC_雪', name: '雪 & <b>Keeper</b>' }],
  usage: { status: 'idle', calls: 0 }, trace: [], memory: {}, agenda: [],
})
function chpmFixture(t, request, session = ref('session')) {
  const { useChpmSettings } = load('composables/useChpmSettings.ts', { '@/services/http': { apiFetch: request } })
  const scope = effectScope()
  const state = scope.run(() => useChpmSettings(() => session.value))
  t.after(() => scope.stop())
  return { ...state, scope, session }
}

test('session mode gates notebook controls while legacy Unicode labels remain escaped', async () => {
  let mounted = 0
  const chpm = component('components/game/ChpmSettings.vue', { '@/composables/useChpmSettings': {
    useChpmSettings() {
      mounted++
      return {
        status: ref({ ...status(), notebook: { document: 'INERT_NOTEBOOK_SENTINEL' } }), draft: ref(preferences()),
        busy: ref(false), error: ref(''), minimumCalls: ref(6), budgetWarning: ref(false), historyWarnings: ref([]),
        load() {}, save() {}, selectStandard() {}, setNotebookEnabled() {},
      }
    },
  } })
  const frame = { setup(_props, { slots }) { return () => h('main', Object.values(slots).flatMap(slot => slot())) } }
  const children = Object.fromEntries([
    'SessionMemorySettings', 'VnNarrationSettings', 'SessionContentSettings', 'DynamicLocationSettings',
    'LivingWorldSettings', 'SessionPortraitSettings', 'NarratorSettings',
  ].map(name => [`./${name}.vue`, { default: { render: () => h('div') } }]))
  const modal = component('components/game/SessionSettingsModal.vue', {
    ...children, './SessionSettingsFrame.vue': { default: frame }, './ChpmSettings.vue': { default: chpm },
    '../editor/StoryVisualPresets.vue': { default: { render: () => h('div') } },
  })
  for (const mode of ['rpg', 'chat', 'story', 'vn']) {
    const before = mounted
    const html = await renderToString(createSSRApp({ render: () => h(modal, { mode, sessionId: 'session' }) }))
    assert.equal(mounted - before, Number(mode === 'vn'), mode)
    assert.equal(html.includes('Private NPC notebooks'), mode === 'vn', mode)
    assert.doesNotMatch(html, /INERT_NOTEBOOK_SENTINEL|<b>Keeper/)
    if (mode === 'vn') {
      assert.match(html, /雪 &amp; &lt;b&gt;Keeper&lt;\/b&gt;/)
      assert.doesNotMatch(html, /name="npc-private-notebooks"[^>]* checked/)
    }
  }
})

test('legacy notebook defaults survive template controls and generic adventure PATCH in every mode', async t => {
  const original = preferences(), value = ref(original)
  const defaults = component('components/living-world/NpcPersonalityDefaults.vue', {}, 'defineExpose({ setNotebookEnabled })')
  defaults.render = () => null
  const renderer = createRenderer({
    createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
    insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null,
  })
  let view
  const app = renderer.createApp({ render: () => h(defaults, {
    modelValue: value.value, characters: [], ref: instance => { view = instance },
    'onUpdate:modelValue': next => { value.value = next },
  }) })
  app.mount({})
  t.after(() => app.unmount())
  view.setNotebookEnabled(true)
  await nextTick()
  assert.equal(original.notebook_enabled, undefined)
  assert.equal(original.agent_steps, undefined)
  assert.equal(value.value.agent_steps, 1)
  assert.notEqual(value.value.actor_ids, original.actor_ids)
  const calls = []
  const { adventureService } = load('services/adventureService.ts', { '@/utils/editor_utils': load('utils/editor_utils.ts'), '@/services/http': {
    authHeaders: () => ({ Authorization: 'Bearer fixture' }),
    apiFetch: async (path, init) => { calls.push({ path, init }); return Response.json(JSON.parse(init.body)) },
  } })
  for (const mode of ['rpg', 'chat', 'story', 'vn']) {
    const payload = { rule_enforcement_mode: mode, npc_personality_settings: value.value }
    const saved = await adventureService.updateAdventure('template', payload)
    assert.deepEqual(saved, payload)
    assert.equal(saved.npc_personality_settings.notebook_enabled, true)
    assert.equal(saved.npc_personality_settings.semantic_memory, true)
    assert.equal(saved.npc_personality_settings.npc_concurrency, 2)
  }
  assert.equal(calls.length, 4)
  assert.ok(calls.every(call => call.init.timeoutMs === 60_000 && call.init.method === 'PATCH'))
})

test('a stale notebook settings save cannot overwrite the newly opened session', async t => {
  let finishOldSave
  const calls = [], other = status({ ...preferences(), mode: 'off' }, 9)
  const f = chpmFixture(t, async (path, init) => {
    calls.push({ path, init })
    if (init.method === 'PATCH') return new Promise(resolve => { finishOldSave = resolve })
    return Response.json(path.includes('other') ? other : status())
  })
  await tick()
  assert.equal(f.draft.value.notebook_enabled ?? false, false)
  assert.equal(await f.save(), true)
  assert.equal(calls.length, 1)
  f.setNotebookEnabled(true)
  const pending = f.save()
  f.session.value = 'other 雪'
  await tick()
  assert.equal(calls[1].init.signal.aborted, true)
  finishOldSave(Response.json(status({ ...preferences(), notebook_enabled: true, agent_steps: 1 }, 5)))
  assert.equal(await pending, false)
  assert.equal(f.status.value.revision, 9)
  assert.equal(f.draft.value.notebook_enabled ?? false, false)
  assert.equal(f.draft.value.mode, 'off')
  assert.equal(f.error.value, '')
  assert.equal(calls[2].path, '/adventures/other%20%E9%9B%AA/chpm')
  assert.equal(calls.filter(call => call.init.method === 'PATCH').length, 1)
})

test('Bable Fish and session font changes preserve an unsaved notebook opt-in and its budget', async t => {
  const calls = [], storage = new Map(), attributes = new Map(), styles = new Map([['--session-font', 'Original font']])
  const previous = ['document', 'localStorage'].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)])
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { documentElement: {
    style: { getPropertyValue: key => styles.get(key) ?? '', setProperty: (key, value) => styles.set(key, value), removeProperty: key => styles.delete(key) },
    getAttribute: key => attributes.get(key) ?? null, setAttribute: (key, value) => attributes.set(key, value), removeAttribute: key => attributes.delete(key),
  } } })
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { setItem: (key, value) => storage.set(key, value) } })
  t.after(() => { for (const [key, descriptor] of previous) { if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key] } })
  const http = { apiFetch: async (path, init) => {
    calls.push({ path, init })
    return Response.json(path.endsWith('/chpm') ? status() : { language: JSON.parse(init.body).language, prompt_suggestions: [] })
  } }
  const f = chpmFixture(t, http.apiFetch)
  await tick()
  f.setNotebookEnabled(true)
  const draft = JSON.stringify(f.draft.value), budget = f.minimumCalls.value, fonts = []
  const { useSessionContentLanguage } = load('composables/useSessionContentLanguage.ts', {
    '@/services/http': http, '@/store/auth': { authState: { token: 'fixture' } },
    '@/composables/useNotifications': { useNotifications: () => ({ addNotification() { throw new Error('Unexpected language error') } }) },
  })
  const { useSessionTypography } = load('composables/useSessionTypography.ts', {
    '@/utils/sessionTypography': load('utils/sessionTypography.ts'),
    '@/services/sessionFontStyles': { loadSessionFontStyle: async font => { fonts.push(font) } },
  })
  const language = f.scope.run(() => {
    const controller = useSessionContentLanguage(() => f.session.value, () => true, () => {})
    useSessionTypography(controller.language)
    return controller
  })
  for (const [name, family] of [['Arabic', 'Baloo Bhaijaan 2'], ['Japanese', 'M PLUS Rounded 1c']]) {
    assert.equal(await language.setLanguage(name), true)
    await nextTick()
    assert.equal(attributes.get('data-session-font'), family)
    assert.equal(storage.get('tw_bable_fish_lang'), name)
    assert.equal(JSON.stringify(f.draft.value), draft)
    assert.equal(f.minimumCalls.value, budget)
  }
  assert.deepEqual(fonts, ['alegreya-sans', 'baloo-bhaijaan-2', 'm-plus-rounded-1c'])
  assert.equal(calls.filter(call => call.path.endsWith('/chpm')).length, 1)
  assert.ok(calls.filter(call => call.init.method === 'PATCH').every(call => Object.keys(JSON.parse(call.init.body)).join() === 'language'))
  f.scope.stop()
  assert.equal(styles.get('--session-font'), 'Original font')
  assert.equal(attributes.size, 0)
})

test('manual creation, generated API requests, template start and ADV import never invent notebook data', async () => {
  const calls = []
  const http = { apiFetch: async (path, init) => { calls.push({ path, init }); return Response.json({ adventure_id: 'template', game_id: 'session' }) }, buildApiUrl: path => `/api${path}` }
  const { api } = load('composables/useApi.ts', {
    '@/services/http': http, '@/store/auth': { authState: { token: 'fixture', isAuthenticated: true } },
    '@/store/config': { configState: {} }, '@/services/visualJobs': { runVisualJob() { throw new Error('Unexpected model request') } },
    '@/services/sessionTransfer': load('services/sessionTransfer.ts'),
  })
  const portal = source('views/PortalView.vue')
  const manual = portal.slice(portal.indexOf('async function createEmptyAdventure()'), portal.indexOf('async function onDeleteAllAdventures()'))
  const create = new Function('api', 'errorMsg', 'setLoadingState', 'router', 'activeSection',
    ts.transpileModule(`${manual}; return createEmptyAdventure`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText)
  await create(api, ref(''), () => {}, { push() {} }, ref('templates'))()
  for (const mode of ['rpg', 'chat', 'story', 'vn']) {
    await api.createAdventure({ title: 'Generated fixture', rule_enforcement_mode: mode, original_prompt: 'A quiet archive.' })
  }
  await api.startSessionForTemplate('template')
  const legacy = { version: '1', title: 'Imported fixture', npc_personality_settings: preferences() }
  const file = new File([JSON.stringify(legacy)], 'legacy.adv', { type: 'application/json' })
  await api.importAdv(file)
  assert.deepEqual(JSON.parse(calls[0].init.body), { title: 'New Adventure', skip_generation: true, rule_enforcement_mode: 'rpg' })
  assert.ok(calls.slice(0, 5).every(call => !('npc_personality_settings' in JSON.parse(call.init.body))))
  assert.equal(calls[5].path, '/adventures/template/sessions/start')
  assert.equal(calls[5].init.body, undefined)
  assert.ok(calls[6].init.body instanceof FormData)
  assert.deepEqual(JSON.parse(await calls[6].init.body.get('file').text()), legacy)
  assert.equal(calls[6].init.headers.has('Content-Type'), false)
  assert.equal(calls[6].init.headers.get('Authorization'), 'Bearer fixture')
})
