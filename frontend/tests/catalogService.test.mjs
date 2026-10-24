import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import ts from 'typescript'

// Exercise the actual service with Vue refs; external requests are replaced.
const requests = []
const apiModule = `data:text/javascript;base64,${Buffer.from('export const api = {}').toString('base64')}`
const { api } = await import(apiModule)
Object.assign(api, {
  generateCatalogImage: async body => {
    requests.push(body)
    return { status: 'success', image_url: '/data/mock.png' }
  },
  uploadCatalogImage: async body => {
    requests.push({ target_id: body.get('target_id') })
    return { status: 'success', image_url: '/data/upload.png' }
  },
  saveImageStylesCatalog: async items => requests.push(structuredClone(items))
})
const source = readFileSync(new URL('../src/services/catalogService.ts', import.meta.url), 'utf8')
const compiled = ts
  .transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext }
  })
  .outputText.replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
  .replace("from '@/composables/useApi'", `from '${apiModule}'`)
const { catalogService: service } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`
)

test('different localized names and repeated names get separate UUIDs', () => {
  service.hydrateCatalogs({})
  for (const name of ['Акварель', 'Нуар', '森', 'Акварель']) service.saveItem('styles', { name })
  const items = service.imageStylesCatalog.value
  assert.equal(new Set(items.map(item => item.id)).size, 4)
  for (const item of items) assert.match(item.id, /^[a-f0-9-]{36}$/)
  assert.deepEqual(
    items.map(item => item.name),
    ['Акварель', 'Нуар', '森', 'Акварель']
  )
})

test('renaming an existing tile preserves its saved ID', () => {
  service.hydrateCatalogs({ image_styles_catalog: [{ id: 'старый-id', name: 'До' }] })
  service.saveItem('styles', { id: 'старый-id', name: 'After' }, 0)
  assert.equal(service.imageStylesCatalog.value[0].id, 'старый-id')
})

test('generate, upload, save and reload keep the same new tile ID', async () => {
  service.hydrateCatalogs({})
  requests.length = 0
  const item = { name: 'Акварель' }
  await service.generateImage('styles', item, 'mock-model')
  const id = item.id
  await service.generateImage('styles', item, 'mock-model')
  await service.uploadImage(
    { target: { files: [new File(['fixture'], 'рисунок.png', { type: 'image/png' })] } },
    'styles',
    item
  )
  service.saveItem('styles', item)
  const snapshot = JSON.parse(JSON.stringify(service.imageStylesCatalog.value))
  service.hydrateCatalogs({ image_styles_catalog: snapshot })
  assert.ok(id)
  assert.deepEqual(
    requests.map(request => request.target_id),
    [id, id, id]
  )
  assert.equal(service.imageStylesCatalog.value[0].id, id)
  assert.equal(service.imageStylesCatalog.value[0].image_url, '/data/upload.png')
})
