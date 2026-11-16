import { test } from 'node:test'
import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { readFileSync } from 'node:fs'
import ts from 'typescript'
const source = readFileSync(new URL('../src/views/PortalView.vue', import.meta.url), 'utf8')
const script = source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
const ast = ts.createSourceFile('PortalView.ts', script, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
const names = ['createEmptyAdventure', 'onDeleteAllAdventures', 'onDeleteAllSessions']
const handlers = ast.statements.filter(n => ts.isFunctionDeclaration(n) && names.includes(n.name?.text)).map(n => n.getText(ast)).join('\n')
const binding = ast.statements.find(n => ts.isVariableStatement(n) && n.getText(ast).includes('= usePortalData()')).getText(ast)
async function portal() {
  // Real handlers and composable bindings, isolated from unrelated portal UI.
  const module = `import {ref} from '${import.meta.resolve('vue')}';
    const state={templates:ref([]),sessions:ref([]),isDeleting:ref(false),isDeletingSession:ref(false),errorMsg:ref(''),isImporting:ref(false)};
    const loading=ref(false); const usePortalData=()=>({...state,setLoadingState:v=>{loading.value=v}});
    ${binding}
    const showDeleteAllAdventuresConfirm=ref(false),showDeleteAllSessionsConfirm=ref(false),activeSection=ref('templates');
    const router={push:()=>{throw new Error('Unexpected navigation')}};
    const api={createAdventure:async()=>{throw new Error('Creation unavailable')}};
    const console={error:()=>{}};
    ${handlers}
    export {state,loading,errorMsg,isImporting,showDeleteAllAdventuresConfirm,showDeleteAllSessionsConfirm,${names.join(',')}};`
  const code=ts.transpileModule(module,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
  return import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}#${Math.random()}`)
}
test('failed creation reports an error and clears loading',async()=>{
  const v=await portal(); await v.createEmptyAdventure()
  assert.equal(v.errorMsg.value,'Creation unavailable'); assert.equal(v.loading.value,false)
})
test('empty collections do not open delete-all dialogs',async()=>{
  const v=await portal(); await v.onDeleteAllAdventures(); await v.onDeleteAllSessions()
  assert.equal(v.showDeleteAllAdventuresConfirm.value,false); assert.equal(v.showDeleteAllSessionsConfirm.value,false)
  v.state.templates.value=[{id:'t'}]; v.state.sessions.value=[{id:'s'}]
  await v.onDeleteAllAdventures(); await v.onDeleteAllSessions()
  assert.equal(v.showDeleteAllAdventuresConfirm.value,true); assert.equal(v.showDeleteAllSessionsConfirm.value,true)
})
test('import progress uses the composable ref',async()=>{
  const v=await portal(); v.state.isImporting.value=true; assert.equal(v.isImporting.value,true)
})
