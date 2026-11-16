import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const code = ts.transpileModule(readFileSync(new URL('../src/utils/conditionSnapshot.ts', import.meta.url), 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
const { conditionSnapshot } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
test('the latest source keeps simultaneous independent facts and retains older active records', () => {
  const injury = { id: 'wound', detail: 'A recorded cut.', updated_revision: 1, observed_message_id: 'earlier' }
  const dirt = { id: 'dirt', detail: 'Dust remains.', updated_revision: 2, observed_message_id: 'latest' }
  const pain = { id: 'pain', detail: 'A recorded ache.', updated_revision: 3, observed_message_id: 'latest' }
  const rows = [injury, dirt, pain], original = structuredClone(rows)
  assert.deepEqual(conditionSnapshot(rows), { current: [pain, dirt], retained: [injury] })
  assert.deepEqual(rows, original)
})
test('legacy observations keep all facts when source ordering is unavailable', () => {
  const rows = [{ id: 'one', detail: 'A cut.' }, { id: 'two', detail: 'Dust.' }]
  assert.deepEqual(conditionSnapshot(rows), { current: rows, retained: [] })
})
test('manual updates without a narration ID use their explicit revision without merging unknown sources', () => {
  const rows = [{ id: 'one', detail: 'A cut.', updated_revision: 1 }, { id: 'two', detail: 'Dust.', updated_revision: 2 }]
  assert.deepEqual(conditionSnapshot(rows), { current: [rows[1]], retained: [rows[0]] })
})
