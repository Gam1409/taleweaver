import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import { ref } from 'vue'
import ts from 'typescript'

const source = readFileSync(new URL('../src/composables/usePromptSuggestions.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
}).outputText.replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replace("import { authState } from '@/store/auth';", 'const authState = { token: "test-token" };')
const { usePromptSuggestions } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)

const oldIdeas = ['Осмотреть зал', 'Проверить рюкзак', 'Поговорить с Линой']
const newIdeas = ['Прислушаться к шагам', 'Осмотреть меч', 'Исследовать стену']
function fixture() {
  const session = ref('одинокий-путник')
  const available = ref(true)
  const ideas = ref([...oldIdeas])
  return { session, available, ideas, ...usePromptSuggestions(() => session.value, () => available.value, ideas) }
}
const response = (ideas = newIdeas) => new Response(JSON.stringify({ suggestions: ideas }))

test('one independent POST stays busy until completion and updates Russian ideas', async t => {
  const f = fixture()
  let complete
  const calls = []
  t.mock.method(globalThis, 'fetch', (url, options) => {
    calls.push({ url, options })
    return new Promise(resolve => { complete = resolve })
  })
  t.mock.timers.enable({ apis: ['setTimeout'] })
  const pending = f.refreshSuggestions()
  t.mock.timers.tick(2000)
  assert.equal(f.suggestionsLoading.value, true)
  await f.refreshSuggestions()
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, `/api/adventures/${encodeURIComponent(f.session.value)}/suggestions`)
  assert.equal(calls[0].options.method, 'POST')
  assert.equal(calls[0].options.headers.Authorization, 'Bearer test-token')
  assert.deepEqual(f.ideas.value, oldIdeas)
  complete(response())
  await pending
  assert.deepEqual(f.ideas.value, newIdeas)
  assert.equal(f.suggestionsLoading.value, false)
  assert.equal(f.suggestionsNotice.value, 'Ideas updated.')
})

for (const status of [401, 404, 409, 500, 502, 504]) {
  test(`HTTP ${status} is visible, preserves ideas and allows retry`, async t => {
    const f = fixture()
    t.mock.method(globalThis, 'fetch', async () => new Response('failure', { status }))
    await f.refreshSuggestions()
    assert.ok(f.suggestionsError.value)
    assert.equal(f.suggestionsLoading.value, false)
    assert.deepEqual(f.ideas.value, oldIdeas)
    globalThis.fetch.mock.mockImplementation(async () => response())
    await f.refreshSuggestions()
    assert.equal(f.suggestionsError.value, '')
    assert.deepEqual(f.ideas.value, newIdeas)
  })
}

test('identical output explains why the list has not changed', async t => {
  const f = fixture()
  t.mock.method(globalThis, 'fetch', async () => response([...oldIdeas].reverse()))
  await f.refreshSuggestions()
  assert.match(f.suggestionsNotice.value, /same ideas/)
})

test('malformed output does not clear the previous list', async t => {
  const f = fixture()
  t.mock.method(globalThis, 'fetch', async () => response([null]))
  await f.refreshSuggestions()
  assert.match(f.suggestionsError.value, /no usable ideas/)
  assert.deepEqual(f.ideas.value, oldIdeas)
})

test('timeout aborts the request and leaves a retryable error', async t => {
  const f = fixture()
  t.mock.timers.enable({ apis: ['setTimeout'] })
  t.mock.method(globalThis, 'fetch', (url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  }))
  const pending = f.refreshSuggestions()
  t.mock.timers.tick(95000)
  await pending
  assert.match(f.suggestionsError.value, /timed out/)
  assert.equal(f.suggestionsLoading.value, false)
  assert.deepEqual(f.ideas.value, oldIdeas)
})

test('changing sessions or starting a turn discards late results', async t => {
  const f = fixture()
  const pendingResponses = []
  t.mock.method(globalThis, 'fetch', (url, options) => new Promise(resolve => {
    pendingResponses.push({ resolve, signal: options.signal })
  }))
  const first = f.refreshSuggestions()
  f.resetSuggestionsRequest()
  assert.equal(pendingResponses[0].signal.aborted, true)
  f.session.value = 'another-session'
  const second = f.refreshSuggestions()
  pendingResponses[0].resolve(response())
  await first
  assert.deepEqual(f.ideas.value, oldIdeas)
  assert.equal(f.suggestionsLoading.value, true)
  pendingResponses[1].resolve(response(['New session ideas']))
  await second
  assert.deepEqual(f.ideas.value, ['New session ideas'])
})

test('refresh does not make a request during an active game turn', async t => {
  const f = fixture()
  const fetch = t.mock.method(globalThis, 'fetch', async () => response())
  f.available.value = false
  await f.refreshSuggestions()
  assert.equal(fetch.mock.callCount(), 0)
  assert.equal(f.suggestionsLoading.value, false)
})
