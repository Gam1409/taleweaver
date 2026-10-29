import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const source = readFileSync(new URL('../src/services/visualJobProgress.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
}).outputText.replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
const progress = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

test('only allowed enabled stages are shown and concurrent jobs stay independent', () => {
  progress.updateVisualProgress('disabled', null)
  progress.updateVisualProgress('unknown', 'private server error')
  assert.deepEqual(progress.visualJobProgress.value, {})
  progress.updateVisualProgress('one', 'prompt')
  progress.updateVisualProgress('two', 'waiting')
  assert.equal(Object.keys(progress.visualJobProgress.value).length, 2)
  assert.equal(progress.visualJobProgress.value.one, 'Preparing the image prompt…')
  progress.clearVisualProgress('one')
  assert.ok(progress.visualJobProgress.value.two)
  progress.clearVisualProgress('two')
  assert.deepEqual(progress.visualJobProgress.value, {})
})
