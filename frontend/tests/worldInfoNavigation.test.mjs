import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { effectScope, ref } from 'vue'
import ts from 'typescript'
const source = ts.transpileModule(readFileSync(new URL('../src/composables/useWorldInfoEntryNavigation.ts', import.meta.url), 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText.replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
const { useWorldInfoEntryNavigation } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)
test('foreground publication and bulk changes cannot open a detail that their completion will clear', async t => {
  const scope = effectScope(), calls = []
  t.after(() => scope.stop())
  const controller = { data: { busy: 'Publishing selected entries…' }, openEntry: async id => calls.push(id) }
  const dialog = ref({ close() { calls.push('close') }, querySelectorAll: () => [] })
  const navigation = scope.run(() => useWorldInfoEntryNavigation(dialog, controller, ref('session-a')))
  await navigation.openEntry('entry-a')
  controller.data.busy = 'Applying confirmed changes…'
  await navigation.openEntry('entry-b')
  assert.deepEqual(calls, [])
  assert.equal(navigation.entryOpen.value, false)
  controller.data.busy = ''
  controller.data.state = { sources: [{ job: { status: 'processing' } }] }
  await navigation.openEntry('entry-c')
  assert.deepEqual(calls, ['close', 'entry-c'])
  assert.equal(navigation.entryOpen.value, true)
})
