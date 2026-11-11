import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { effectScope, reactive, nextTick } from 'vue'
import ts from 'typescript'

const quoteCode = ts.transpileModule(readFileSync(new URL('../src/utils/wardrobeQuotes.ts', import.meta.url), 'utf8'),
  {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext}}).outputText
const quoteModule = `data:text/javascript;base64,${Buffer.from(quoteCode).toString('base64')}`
const {quoteError, quoteSuggestion} = await import(quoteModule)
const source = readFileSync(new URL('../src/components/game/DebugWardrobeCorrection.vue', import.meta.url), 'utf8')
  .match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
  .replace(/import type[^\n]+\n/, '')
  .replace(/const props = defineProps<[\s\S]*?>\(\)/, '')
  .replace(/const emit = defineEmits<[^\n]+\n/, '')
  .replace(/import[^\n]+\n/g, '')
const compiled = ts.transpileModule(`import {computed,ref,watch} from '${import.meta.resolve('vue')}';
import {quoteError,quoteSuggestion} from '${quoteModule}';
export function setup(props, emit) {
  ${source}
  return { status, evidence, placement, uncovered, restoreCoverage, valid, submit, itemError, placementError, regionError, regionChoices, useSelection, canUseSelection, resetExposedRegions };
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

test('a correction sends the explicitly selected source message without applying an item', async t => {
  const f = fixture(t)
  f.props.sourceMessageId = 'correct-source'
  f.props.source = 'Lina carries black shoes.'
  f.status.value = 'carried'
  await nextTick()
  f.evidence.value = f.props.source
  f.submit()
  assert.equal(f.calls.length, 1)
  assert.match(f.calls[0][1], /^\/debug wardrobe_correct preview 2 /)
  const payload = JSON.parse(f.calls[0][1].slice('/debug wardrobe_correct preview 2 '.length))
  assert.equal(payload.source_message_id, 'correct-source')
  assert.equal(payload.evidence, 'Lina carries black shoes.')
})

test('restored coverage requires an explicit choice and a literal restoring quote', t => {
  const f = fixture(t)
  const quote = 'Lina pulls the garment back into place.'
  f.props.source = quote
  f.status.value = 'worn'
  f.evidence.value = quote
  f.placement.value = quote
  f.uncovered.value = []
  assert.equal(f.valid.value, false)
  f.restoreCoverage.value = true
  assert.equal(f.valid.value, true)
  f.submit()
  const body = JSON.parse(f.calls[0][1].slice('/debug wardrobe_correct preview 2 '.length))
  assert.equal(body.restore_coverage, true)
  assert.deepEqual(body.uncovered_regions, [])
  f.placement.value = 'Not in the source.'
  assert.equal(f.valid.value, false)
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

test('a filled form identifies which quote does not match instead of a generic disabled button', t => {
  const f = fixture(t)
  f.status.value = 'worn'
  f.evidence.value = 'red briefs'
  f.placement.value = 'They are lowered to her knees'
  assert.equal(f.itemError.value, '')
  assert.equal(f.placementError.value, '')
  f.placement.value = 'They are lowered to her Knees'
  assert.equal(f.valid.value, false)
  assert.match(f.placementError.value, /not found.*cited message/i)
  assert.equal(f.itemError.value, '')
})

test('invalid inherited exposed regions stay visible so the user can remove them', t => {
  const f = fixture(t)
  f.uncovered.value = ['pelvis', 'feet']
  assert.match(f.regionError.value, /feet/)
  assert.ok(f.regionChoices.value.includes('feet'))
  f.resetExposedRegions()
  assert.deepEqual(f.uncovered.value, [])
  assert.equal(f.placement.value, '')
})

test('the same exact Russian quote can identify both the item and its partial placement', t => {
  const f = fixture(t)
  const quote = 'Стринги сползли до колен доктора Рин'
  f.props.source = `Она остановилась. ${quote}. Затем они заговорили.`
  f.status.value = 'worn'
  f.evidence.value = quote
  f.placement.value = quote
  assert.equal(f.valid.value, true)
  f.submit()
  assert.equal(f.calls.length, 1)
})

test('source suggestions preserve the original case and whitespace and still require exact evidence', () => {
  const original = 'стринги  сползли\nдо колен доктора Рин'
  const typed = 'Стринги сползли до колен доктора Рин'
  const source = `Она остановилась. ${original}. Затем они заговорили.`
  assert.ok(quoteError(source, typed))
  assert.equal(quoteSuggestion(source, typed), original)
  assert.equal(quoteError(source, original), '')
  assert.equal(quoteSuggestion('prefix [A+B]  (coat).', '[a+b] (coat)'), '[A+B]  (coat)')
})

test('quote assistance never chooses ambiguous matches or joins fragments', () => {
  assert.equal(quoteSuggestion('red briefs; RED BRIEFS.', 'Red Briefs'), '')
  assert.equal(quoteSuggestion('A A A', 'a a'), '')
  assert.equal(quoteSuggestion('red silk briefs, lowered to the knees.', 'red... briefs'), '')
  assert.equal(quoteSuggestion('red silk briefs.', 'green silk briefs'), '')
})

test('quote lengths agree with the server Unicode character limits', () => {
  const source = '🌸'.repeat(801)
  assert.ok(quoteError(source, '🌸'.repeat(3)))
  assert.equal(quoteError(source, '🌸'.repeat(800)), '')
  assert.ok(quoteError(source, '🌸'.repeat(801)))
})

test('only an exact source selection can populate quote fields', t => {
  const f = fixture(t)
  f.props.selectedQuote = 'Red Briefs'
  assert.equal(f.canUseSelection.value, false)
  f.useSelection('item')
  assert.equal(f.evidence.value, 'Red... briefs.')
  f.props.selectedQuote = 'red briefs'
  assert.equal(f.canUseSelection.value, true)
  f.useSelection('item')
  f.useSelection('placement')
  assert.equal(f.evidence.value, 'red briefs')
  assert.equal(f.placement.value, 'red briefs')
})

test('copying edge whitespace submits the same canonical quotes the server revalidates', t => {
  const f = fixture(t)
  f.status.value = 'worn'
  f.evidence.value = '\n  red briefs \n'
  f.placement.value = '\tThey are lowered to her knees.\n'
  assert.equal(f.valid.value, true)
  f.submit()
  const payload = JSON.parse(f.calls[0][1].split(' ').slice(4).join(' '))
  assert.equal(payload.evidence, 'red briefs')
  assert.equal(payload.placement_evidence, 'They are lowered to her knees.')
})
