import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { effectScope, reactive } from 'vue'
import ts from 'typescript'

const script = readFileSync(new URL('../src/components/game/DebugWardrobeRecovery.vue', import.meta.url), 'utf8')
  .match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  .replace(/import[^\n]+\n/g, '')
  .replace(/const props = defineProps<[\s\S]*?>\(\)/, '')
  .replace(/const emit = defineEmits<[^\n]+\n/, '')
  .replace('export interface WardrobeRecoveryPreview', 'interface WardrobeRecoveryPreview')
const compiled = ts.transpileModule(`import {computed,ref,watch} from '${import.meta.resolve('vue')}';
export function setup(props, emit) {
  ${script}
  return {recoveryFocus, modelRole, focusError, requestPreview};
}`, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext}}).outputText
const {setup} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

function fixture(t) {
  const props = reactive({npcId: 'LINA', busy: false})
  const commands = []
  const scope = effectScope()
  t.after(() => scope.stop())
  return {props, commands, ...scope.run(() => setup(props, (_event, command) => commands.push(command)))}
}

test('an optional quoted search hint travels in one preview command and does not apply items', t => {
  const f = fixture(t)
  f.recoveryFocus.value = '  пробирка "стеклянная"  '
  f.modelRole.value = 'small'
  f.requestPreview()
  assert.deepEqual(f.commands, ['/debug wardrobe_preview "LINA" small ' + JSON.stringify('пробирка "стеклянная"')])
  f.props.busy = true
  f.requestPreview()
  assert.equal(f.commands.length, 1)
})

test('the old preview command remains valid without a focus and excessive focus is rejected', t => {
  const f = fixture(t)
  f.requestPreview()
  assert.equal(f.commands[0], '/debug wardrobe_preview "LINA" complex')
  f.recoveryFocus.value = '🌸'.repeat(400)
  assert.equal(f.focusError.value, false)
  f.requestPreview()
  f.recoveryFocus.value += '🌸'
  assert.equal(f.focusError.value, true)
  f.requestPreview()
  assert.equal(f.commands.length, 2)
})
