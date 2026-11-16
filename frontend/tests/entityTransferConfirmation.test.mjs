import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import ts from 'typescript'
import { effectScope, ref } from 'vue'

const compiled = ts.transpileModule(readFileSync(new URL('../src/composables/useEntityTransfer.ts', import.meta.url), 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText
  .replaceAll("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replace("import { entityService } from '@/services/entityService';", 'const entityService = {};')
  .replace("import { notificationService } from '@/services/notificationService';", 'const notificationService = {};')
  .replace("import { makeSafeFilename } from '@/utils/editor_utils';", 'const makeSafeFilename = value => value;')
const { useEntityTransfer } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

function setup(t) {
  const original = globalThis.document
  const inputs = []
  globalThis.document = { createElement: () => {
    const input = { clicks: 0, click() { this.clicks += 1 } }
    inputs.push(input)
    return input
  } }
  const scope = effectScope(), adventure = ref('first-adventure')
  const transfer = scope.run(() => useEntityTransfer(() => adventure.value, async () => {}))
  t.after(() => { scope.stop(); globalThis.document = original })
  return { transfer, inputs, adventure, scope }
}

test('protagonist replacement waits for confirmation and cancel opens no file picker', t => {
  const { transfer, inputs } = setup(t)
  transfer.importEntity('protagonist')
  assert.equal(transfer.isProtagonistImportPending.value, true)
  assert.equal(inputs.length, 0)
  transfer.cancelProtagonistImport()
  assert.equal(transfer.isProtagonistImportPending.value, false)
  transfer.confirmProtagonistImport()
  assert.equal(inputs.length, 0)
})

test('accepted replacement opens the original bundle picker once', t => {
  const { transfer, inputs } = setup(t)
  transfer.importEntity('protagonist')
  transfer.confirmProtagonistImport()
  assert.equal(transfer.isProtagonistImportPending.value, false)
  assert.equal(inputs.length, 1)
  assert.equal(inputs[0].type, 'file')
  assert.equal(inputs[0].accept, '.twe')
  assert.equal(inputs[0].clicks, 1)
  transfer.confirmProtagonistImport()
  assert.equal(inputs.length, 1)
})

test('NPC and item imports retain their direct file selection flow', t => {
  const { transfer, inputs } = setup(t)
  transfer.importEntity('npc')
  transfer.importEntity('item')
  assert.equal(transfer.isProtagonistImportPending.value, false)
  assert.equal(inputs.length, 2)
  assert.ok(inputs.every(input => input.accept === '.twe' && input.clicks === 1))
})

test('changing or leaving the adventure cancels its pending replacement', t => {
  const { transfer, inputs, adventure, scope } = setup(t)
  transfer.importEntity('protagonist')
  adventure.value = 'second-adventure'
  assert.equal(transfer.isProtagonistImportPending.value, false)
  transfer.confirmProtagonistImport()
  assert.equal(inputs.length, 0)
  transfer.importEntity('protagonist')
  scope.stop()
  assert.equal(transfer.isProtagonistImportPending.value, false)
})
