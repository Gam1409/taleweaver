import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import { effectScope } from 'vue'
import ts from 'typescript'

const compile = path => ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText.replace(/^import ['"].*\.css['"];\s*$/gm, '').replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
const uri = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
const workspaceUri = uri(compile('../src/composables/useWorkspaceTheme.ts'))
const { useWorkspaceTheme } = await import(workspaceUri)
const { useAuthoringTheme } = await import(uri(compile('../src/composables/useAuthoringTheme.ts').replace("from './useWorkspaceTheme'", `from '${workspaceUri}'`)))

test('overlapping routes retain shared styling and dispose authoring-only dialog styling', t => {
  const previous = globalThis.document
  const dataset = {}
  globalThis.document = { documentElement: { dataset } }
  t.after(() => { globalThis.document = previous })
  const portal = effectScope(), firstEditor = effectScope(), secondEditor = effectScope()
  portal.run(useWorkspaceTheme)
  firstEditor.run(useAuthoringTheme)
  secondEditor.run(useAuthoringTheme)
  firstEditor.stop()
  assert.equal(dataset.authoringTheme, 'archive')
  secondEditor.stop()
  assert.equal(dataset.authoringTheme, undefined)
  assert.equal(dataset.workspaceTheme, 'archive')
  portal.stop()
  assert.equal(dataset.workspaceTheme, undefined)
})
