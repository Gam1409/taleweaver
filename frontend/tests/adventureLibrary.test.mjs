import { test } from 'node:test'
import { Buffer } from 'node:buffer'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { createRequire } from 'node:module'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const dataModule = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
const mockUrl = dataModule(
  'export const mock = {}; export const apiFetch = (...args) => mock.fetch(...args)'
)
const { mock } = await import(mockUrl)
function compile(path, substitutions = {}) {
  let source = ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 }
  }).outputText
  for (const [from, to] of Object.entries(substitutions))
    source = source.replaceAll(`'${from}'`, `'${to}'`)
  return dataModule(source)
}
const serviceUrl = compile('../src/services/adventureLibrary.ts', { '@/services/http': mockUrl })
const { adventureLibraryService: service } = await import(serviceUrl)
const publicationUrl = compile('../src/services/adventurePublication.ts', {
  '@/services/http': mockUrl
})
const { adventurePublicationService: publication } = await import(publicationUrl)
const vueUrl = pathToFileURL(require.resolve('vue/dist/vue.runtime.esm-bundler.js')).href
const { useAdventureLibrary } = await import(
  compile('../src/composables/useAdventureLibrary.ts', {
    vue: vueUrl,
    '@/services/adventureLibrary': serviceUrl
  })
)
const item = (id, installed = null, update = false) => ({
  entry: { id, title: id, version: '2', size_bytes: 10 },
  installed_version: installed,
  update_available: update
})
const ok = body => ({ ok: true, json: async () => body })

test('catalog and publication requests use scoped routes, explicit export acknowledgment and long install timeout', async () => {
  const requests = []
  mock.fetch = async (path, init = {}) => {
    requests.push([path, init])
    return { ...ok({}), blob: async () => new Blob(['zip']) }
  }
  await service.fetchCatalog()
  await service.refreshCatalog()
  await service.install('world')
  await publication.preview('world/id')
  await publication.export('world/id', true)
  assert.deepEqual(
    requests.map(([path]) => path),
    [
      '/adventures/library/catalog',
      '/adventures/library/refresh',
      '/adventures/library/install',
      '/adventures/templates/world%2Fid/publication/preview',
      '/adventures/templates/world%2Fid/publication/export'
    ]
  )
  assert.deepEqual(JSON.parse(requests[2][1].body), { id: 'world' })
  assert.equal(requests[2][1].timeoutMs, 600000)
  assert.deepEqual(JSON.parse(requests[4][1].body), { acknowledge_changes: true })
})

test('proxy HTML is not exposed as a catalog error', async () => {
  mock.fetch = async () => ({
    ok: false,
    status: 502,
    text: async () => '<html>proxy debug</html>'
  })
  await assert.rejects(
    service.fetchCatalog(),
    error => error.status === 502 && !error.message.includes('proxy debug')
  )
})

test('selection permits new installs and updates but never accidental downgrade', async () => {
  mock.fetch = async () =>
    ok({
      items: [item('new'), item('update', '1', true), item('current', '2'), item('newer', '3')],
      stale: false
    })
  const lib = useAdventureLibrary()
  await lib.openDialog()
  lib.selectAll()
  assert.deepEqual([...lib.selectedIds.value], ['new', 'update'])
  assert.equal(lib.selectedTotalBytes.value, 20)
  lib.toggle('newer')
  assert.equal(lib.selectedCount.value, 2)
})

test('failed catalog load is retryable and clears the old error', async () => {
  mock.fetch = async () => {
    throw new Error('offline')
  }
  const lib = useAdventureLibrary()
  await lib.openDialog()
  assert.match(lib.error.value, /network/)
  mock.fetch = async () => ok({ items: [item('new')], stale: true })
  await lib.load()
  assert.equal(lib.error.value, null)
  assert.equal(lib.staleCatalog.value, true)
})

test('installation locks close and duplicate submission and awaits the portal reload', async () => {
  let release,
    imports = 0,
    reloaded = false
  mock.fetch = async path => {
    if (path.endsWith('/install')) {
      imports++
      await new Promise(resolve => {
        release = resolve
      })
      return ok({ template_id: 'local', version: '2' })
    }
    return ok({ items: [item('new', imports ? '2' : null)], stale: false })
  }
  const lib = useAdventureLibrary({
    onInstalled: async () => {
      reloaded = true
    }
  })
  await lib.openDialog()
  lib.selectAll()
  const pending = lib.downloadSelected()
  await Promise.resolve()
  lib.closeDialog()
  await lib.downloadSelected()
  assert.equal(lib.isOpen.value, true)
  assert.equal(imports, 1)
  release()
  await pending
  assert.equal(reloaded, true)
  assert.equal(lib.isSubmitting.value, false)
  assert.equal(lib.items.value[0].installed_version, '2')
})

test('partial install errors remain visible while successful items refresh', async () => {
  const attempts = []
  let refreshes = 0
  mock.fetch = async (path, init) => {
    if (!path.endsWith('/install')) return ok({ items: [item('bad'), item('good')], stale: false })
    const { id } = JSON.parse(init.body)
    attempts.push(id)
    return id === 'bad'
      ? {
          ok: false,
          status: 422,
          text: async () => JSON.stringify({ detail: 'Unsupported story format.' })
        }
      : ok({ template_id: 'local', version: '2' })
  }
  const lib = useAdventureLibrary({
    onInstalled: async () => {
      refreshes++
    }
  })
  await lib.openDialog()
  lib.selectAll()
  await lib.downloadSelected()
  assert.deepEqual(attempts, ['bad', 'good'])
  assert.equal(refreshes, 1)
  assert.match(lib.installErrors.value[0], /bad: Unsupported story format/)
})
