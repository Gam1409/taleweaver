import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { effectScope, reactive, nextTick } from 'vue'
import ts from 'typescript'

const source = readFileSync(new URL('../src/components/game/DebugWardrobeCorrection.vue', import.meta.url), 'utf8')
  .match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  .replace(/import type[^\n]+\n/, '')
  .replace(/const props = defineProps<[\s\S]*?>\(\)/, '')
  .replace(/const emit = defineEmits<[^\n]+\n/, '')
  .replace(/import[^\n]+\n/, '')
const compiled = ts.transpileModule(`import {computed,ref,watch} from '${import.meta.resolve('vue')}';
export function setup(props, emit) {
  ${source}
  return { status, evidence, placement, uncovered, valid, submit };
}`, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext}}).outputText
const { setup } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

function fixture(t) {
  const calls = []
  const props = reactive({ token: 'preview', busy: false, source: 'Lina wears red briefs. They are lowered to her knees.',
    entry: {index: 2, evidence: 'Red... briefs.', placement_evidence: 'lowered...knees', uncovered_regions: ['pelvis'], coverage: ['pelvis']} })
  const scope = effectScope()
  t.after(() => scope.stop())
  return { props, calls, ...scope.run(() => setup(props, (...args) => calls.push(args))) }
}

test('correction requires an explicit state and exact quotes before emitting a preview-only command', t => {
  const f = fixture(t)
  f.submit()
  assert.equal(f.calls.length, 0)
  f.status.value = 'worn'
  f.evidence.value = 'red briefs'
  f.placement.value = 'They are lowered to her knees.'
  assert.equal(f.valid.value, true)
  f.submit()
  assert.equal(f.calls.length, 1)
  assert.equal(f.calls[0][0], 'command')
  const prefix = '/debug wardrobe_correct preview 2 '
  assert.ok(f.calls[0][1].startsWith(prefix))
  assert.deepEqual(JSON.parse(f.calls[0][1].slice(prefix.length)), {
    status: 'worn', evidence: 'red briefs', uncovered_regions: ['pelvis'], placement_evidence: 'They are lowered to her knees.'
  })
  f.props.busy = true
  f.submit()
  assert.equal(f.calls.length, 1)
})

test('paraphrased evidence and regions outside garment coverage cannot be submitted', t => {
  const f = fixture(t)
  f.status.value = 'worn'
  f.placement.value = 'They are lowered to her knees.'
  assert.equal(f.valid.value, false)
  f.evidence.value = 'red briefs'
  f.uncovered.value = ['feet']
  f.submit()
  assert.equal(f.calls.length, 0)
})

test('choosing fully removed clears partial placement before validating carried clothing', async t => {
  const f = fixture(t)
  f.evidence.value = 'red briefs'
  f.status.value = 'carried'
  await nextTick()
  assert.deepEqual(f.uncovered.value, [])
  assert.equal(f.placement.value, '')
  assert.equal(f.valid.value, true)
})
