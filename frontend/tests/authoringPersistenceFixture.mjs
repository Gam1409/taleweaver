import { readFileSync, existsSync } from 'node:fs'
import { createRequire } from 'node:module'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, h, ref } from 'vue'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const compile = source => ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
const editorSource = readFileSync(new URL('../src/views/AdventureEditorView.vue', import.meta.url), 'utf8')
const section = (from, to) => editorSource.slice(editorSource.indexOf(from), editorSource.indexOf(to))

export function authoringFixture() {
  const requests = [], cache = new Map()
  function load(path) {
    if (cache.has(path)) return cache.get(path)
    const file = new URL(`../src/${path}.ts`, import.meta.url)
    if (!existsSync(file)) return {}
    const module = { exports: {} }
    new Function('require', 'module', 'exports', compile(readFileSync(file, 'utf8')))(name => {
      if (name === '@/services/http') return {
        authHeaders: () => ({}),
        async apiFetch(path, options) {
          requests.push({ path, method: options.method, data: JSON.parse(options.body) })
          return Response.json({ status: 'success' })
        },
      }
      return name.startsWith('@/') ? load(name.slice(2)) : require(name)
    }, module, module.exports)
    cache.set(path, module.exports)
    return module.exports
  }
  const handlers = [
    section('function closeEditEntityModal()', 'function openAddExistingItem('),
    section('function openCreateNpc(', 'function createNewItemForProtagonist('),
    section('function handleItemTypeSelected(', 'function closeExitEditModal('),
    section('function openTextEdit(', 'async function saveChanges()'),
  ].join('\n')
  const source = `return function fixture(ref, entityService, utils, authoring) {
    const { fixNewlines, itemTypePrefix, sanitizeEditorIdToken } = utils;
    const { createEntityPayload, characterResourceFields, switchScriptFields } = authoring;
    const props={adventureId:'AUTHORING_FIXTURE'}, router={replace(){}}, notices=[];
    const addNotification=(...args)=>notices.push(args), fetchDebugInfo=async()=>{}, fetchAdventure=async()=>{};
    const editForm=ref({}), showEditModal=ref(false), editEntityContext=ref(null), isCreateEntityMode=ref(false);
    const createEntitySceneId=ref(null),createEntityType=ref(null),pendingProtagonistAssignment=ref(null),showItemTypeSelector=ref(false);
    const activeMapSceneId=ref('LAB'), isSavingText=ref(false),promptError=ref(''),referenceOptions=ref([]);
    const debugData=ref({adventure:{start_scene_id:'LAB'},npcs:[],scenes:[{id:'LAB'}]});
    const editorObjects=ref([]),editorTextLogs=ref([]),editorSwitches=ref([]),editorContainers=ref([]),editorScenes=ref([{id:'LAB'}]);
    const openCreateItem=()=>{}, saveProtagonistField=async()=>{};
    ${handlers}
    return {openTextEdit,openCreateNpc,handleItemTypeSelected,saveEntityText,editForm,editEntityContext,
      createEntitySceneId,isCreateEntityMode,debugData,editorObjects,editorSwitches,notices};
  }`
  const state = new Function(compile(source))()(ref, load('services/entityService').entityService, load('utils/editor_utils'), load('services/entityAuthoringPayload'))
  return { ...state, requests, load }
}

export function modalFixture(t, editor, mode = 'rpg') {
  let pending
  const source = readFileSync(new URL('../src/components/editor/EditEntityModal.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  const module = { exports: {} }
  new Function('require', 'module', 'exports', compile(compileScript(descriptor, { id: 'authoring-persistence' }).content))(name => {
    if (name.endsWith('.vue')) return { render: () => null }
    return name.startsWith('@/') ? editor.load(name.slice(2)) : require(name)
  }, module, module.exports)
  const component = module.exports.default
  component.render = () => null
  const renderer = createRenderer({ createElement: () => ({}), createText: () => ({}), createComment: () => ({}),
    insert() {}, remove() {}, setText() {}, setElementText() {}, patchProp() {}, parentNode: () => null, nextSibling: () => null })
  let view
  const app = renderer.createApp({ render: () => h(component, {
    show: true, context: editor.editEntityContext.value, initialForm: editor.editForm.value,
    ruleEnforcementMode: mode, isSaving: false, isCreateEntityMode: editor.isCreateEntityMode.value,
    referenceOptions: [], adventureId: 'AUTHORING_FIXTURE', ref: instance => { if (instance) view = instance.$.setupState },
    onSave: data => { pending = editor.saveEntityText(data) },
  }) })
  app.mount({})
  t.after(() => app.unmount())
  return { view, async submit() { assertSaveable(); view.handleSave(); await pending },
    update(values) { Object.assign(view.localForm, values) },
  }
  function assertSaveable() { if (view.isFormInvalid) throw new Error('Fixture should pass real modal validation') }
}
