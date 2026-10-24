import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import { ref } from 'vue'
import ts from 'typescript'

async function loadModule(name) {
  const source = readFileSync(new URL(`../src/composables/${name}.ts`, import.meta.url), 'utf8')
  const compiled = ts
    .transpileModule(source, {
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
    })
    .outputText.replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  return import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`)
}
const { indexLibrarySessions } = await loadModule('librarySessions')
const { usePortalSessionNavigation } = await loadModule('usePortalSessionNavigation')

function save(gameId, fields = {}) {
  return {
    game_id: gameId,
    template_id: 'forest',
    adventure_id: 'forest',
    adventure_title: 'Forest escape',
    status: 'active',
    created_at: '2026-10-01T10:00:00Z',
    ...fields
  }
}

test('empty library has no resume target', () => {
  assert.equal(indexLibrarySessions([]).size, 0)
})

test('newest active save wins regardless of API order or in-game time', () => {
  const oldest = save('old', { in_game_time: 90000 })
  const newest = save('new', { created_at: '2026-10-04T10:00:00Z', in_game_time: 0 })
  for (const saves of [
    [oldest, newest],
    [newest, oldest]
  ]) {
    assert.equal(indexLibrarySessions(saves).get('forest'), newest)
  }
})

test('active or paused save takes priority over newer completed and defeated sessions', () => {
  const paused = save('paused', { is_paused: true })
  const completed = save('completed', { status: 'completed', created_at: '2026-10-06' })
  const defeated = save('defeated', { status: 'game_over', created_at: '2026-10-07' })
  assert.equal(indexLibrarySessions([completed, paused, defeated]).get('forest'), paused)
})

test('completed and defeated saves remain accessible when no active save exists', () => {
  const completed = save('completed', { status: 'completed' })
  const defeated = save('defeated', { status: 'game_over', created_at: '2026-10-07' })
  assert.equal(indexLibrarySessions([completed]).get('forest'), completed)
  assert.equal(indexLibrarySessions([defeated, completed]).get('forest'), defeated)
})

test('paused backend status is unfinished even without the legacy is_paused flag', () => {
  const paused = save('paused', { status: 'paused', is_paused: false })
  const completed = save('completed', { status: 'completed', created_at: '2026-10-08' })
  assert.equal(indexLibrarySessions([completed, paused]).get('forest'), paused)
})

test('older responses without status or template_id use adventure_id', () => {
  const response = save('compatible', { status: null, template_id: undefined, is_paused: true })
  assert.equal(indexLibrarySessions([response]).get('forest'), response)
})

test('template_id is authoritative; identical adventure titles do not mix saves', () => {
  const other = save('other', { template_id: 'other', adventure_id: 'forest' })
  const index = indexLibrarySessions([save('mine'), other])
  assert.equal(index.get('forest').game_id, 'mine')
  assert.equal(index.get('other'), other)
})

test('archived, detached and invalid sessions do not offer Resume', () => {
  const sessions = [
    save('archive', { status: 'archived' }),
    save('detached', { template_id: null, adventure_id: null }),
    save('')
  ]
  assert.equal(indexLibrarySessions(sessions).size, 0)
})

test('missing or malformed timestamps stay usable but do not outrank dated saves', () => {
  const undated = save('undated', { created_at: undefined })
  const invalid = save('invalid', { created_at: 'not-a-date' })
  const dated = save('dated')
  assert.equal(indexLibrarySessions([undated]).get('forest'), undated)
  assert.equal(indexLibrarySessions([invalid, undated, dated]).get('forest'), dated)
})

test('selection preserves input and follows deletions on refresh', () => {
  const older = Object.freeze(save('older'))
  const newer = Object.freeze(save('newer', { created_at: '2026-10-06' }))
  const input = Object.freeze([older, newer])
  assert.equal(indexLibrarySessions(input).get('forest'), newer)
  assert.equal(input[0], older)
  assert.equal(indexLibrarySessions([older]).get('forest'), older)
  assert.equal(indexLibrarySessions([]).has('forest'), false)
})

function navigationFixture(push = async () => {}) {
  const starts = []
  const data = {
    sessions: ref([save('saved')]),
    templates: ref([{ template_id: 'forest', title: 'Forest escape' }]),
    isStartingSession: ref(false),
    startingSessionTemplateId: ref(null),
    startingSessionTitle: ref(''),
    async startSessionForTemplate(templateId, onStarted) {
      starts.push(templateId)
      data.isStartingSession.value = true
      try {
        await onStarted('new-session')
      } finally {
        data.isStartingSession.value = false
      }
    }
  }
  const routes = []
  const router = {
    async push(route) {
      routes.push(route)
      await push(route)
    }
  }
  return { ...usePortalSessionNavigation(data, router), data, starts, routes }
}

test('Resume routes to the saved ID without creating a session or setting is_new', async () => {
  const nav = navigationFixture()
  await nav.playSession('saved')
  assert.deepEqual(nav.starts, [])
  assert.deepEqual(nav.routes, [
    {
      name: 'game',
      params: { id: 'saved' },
      query: { title: 'Forest escape', resuming: 'true' }
    }
  ])
  assert.equal(nav.data.isStartingSession.value, false)
  assert.equal(nav.isResuming.value, false)
})

test('New session creates a separate game and uses only the is_new flag', async () => {
  const nav = navigationFixture()
  await nav.startSession('forest')
  assert.deepEqual(nav.starts, ['forest'])
  assert.deepEqual(nav.routes, [
    {
      name: 'game',
      params: { id: 'new-session' },
      query: { title: 'Forest escape', is_new: 'true' }
    }
  ])
})

test('rapid Resume and Start clicks cannot misroute a save as a new game', async () => {
  let finish
  const waiting = new Promise(resolve => {
    finish = resolve
  })
  const nav = navigationFixture(() => waiting)
  const resume = nav.playSession('saved')
  assert.equal(nav.isResuming.value, true)
  assert.equal(nav.data.startingSessionTemplateId.value, 'forest')
  await nav.playSession('saved')
  await nav.startSession('forest')
  assert.equal(nav.routes.length, 1)
  assert.deepEqual(nav.starts, [])
  finish()
  await resume
})

test('failed navigation clears busy state so Resume can be retried', async () => {
  const nav = navigationFixture(async () => {
    throw new Error('navigation failed')
  })
  await assert.rejects(nav.playSession('saved'), /navigation failed/)
  assert.equal(nav.data.isStartingSession.value, false)
  assert.equal(nav.isResuming.value, false)
  assert.equal(nav.data.startingSessionTemplateId.value, null)
  assert.equal(nav.data.startingSessionTitle.value, '')
})

test('a removed session is not resumed or silently replaced with a new one', async () => {
  const nav = navigationFixture()
  await nav.playSession('deleted')
  assert.deepEqual(nav.routes, [])
  assert.deepEqual(nav.starts, [])
})
