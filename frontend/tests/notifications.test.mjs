import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const compile = path => ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
}).outputText
const uri = text => `data:text/javascript;base64,${Buffer.from(text).toString('base64')}`
const serviceUrl = uri(compile('../src/services/notificationService.ts').replace("from 'vue'", `from '${import.meta.resolve('vue')}'`))
const { notificationService } = await import(serviceUrl)
const hookUrl = uri(compile('../src/composables/useNotifications.ts').replace("from '@/services/notificationService'", `from '${serviceUrl}'`))
const { useNotifications } = await import(hookUrl)

test('editor and gameplay share IDs, dismissal and one timer lifecycle', t => {
  let nextTimer = 0
  const timers = new Map()
  t.mock.method(globalThis, 'setTimeout', (callback, delay) => {
    timers.set(++nextTimer, { callback, delay })
    return nextTimer
  })
  t.mock.method(globalThis, 'clearTimeout', timer => timers.delete(timer))
  t.after(() => notificationService.clear())
  const gameplay = useNotifications()
  const editorId = notificationService.success('Saved')
  const gameId = gameplay.addNotification('The saved turn was recovered.', 'info')
  assert.notEqual(editorId, gameId)
  assert.equal(gameplay.notifications.value, notificationService.all.value)
  assert.equal(gameplay.notifications.value.length, 2)
  assert.deepEqual([...timers.values()].map(timer => timer.delay), [5000, 8000])
  gameplay.removeNotification(editorId)
  assert.deepEqual(notificationService.all.value.map(note => note.id), [gameId])
  assert.equal(timers.size, 1)
  notificationService.clear()
  assert.equal(timers.size, 0)
  assert.equal(gameplay.notifications.value.length, 0)
})

test('the app owns the single notification renderer', () => {
  const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
  const game = readFileSync(new URL('../src/views/GameView.vue', import.meta.url), 'utf8')
  assert.equal((app.match(/<NotificationToast\b/g) || []).length, 1)
  assert.doesNotMatch(game, /GameNotificationsOverlay/)
})
