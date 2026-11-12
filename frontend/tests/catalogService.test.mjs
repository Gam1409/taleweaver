import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { Buffer } from 'node:buffer'
import ts from 'typescript'
import { uuidModule } from './uuidModule.mjs'

// Exercise the actual service with Vue refs; external requests are replaced.
const requests = []
const apiModule = `data:text/javascript;base64,${Buffer.from('export const api = {}').toString('base64')}`
const { api } = await import(apiModule)
const confirmationModule = `data:text/javascript;base64,${Buffer.from('export const confirmation = { approved: true }; export const confirmAction = async () => confirmation.approved').toString('base64')}`
const { confirmation } = await import(confirmationModule)
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
  .replace("from '@/utils/uuid'", `from '${uuidModule}'`)
  .replace("from './confirmAction'", `from '${confirmationModule}'`)
const { catalogService: service } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`
)

test('catalog removal respects cancellation and removes only the selected catalog item', async () => {
  service.hydrateCatalogs({
    image_styles_catalog: [{ id: 'style', name: 'Watercolour' }],
    tone_catalog: [{ id: 'mystery', name: 'Mystery' }, { id: 'wonder', name: 'Wonder' }]
  })
  confirmation.approved = false
  assert.equal(await service.removeItem('tones', 0), false)
  assert.equal(service.toneCatalog.value.length, 2)
  confirmation.approved = true
  assert.equal(await service.removeItem('tones', 0), true)
  assert.deepEqual(service.toneCatalog.value.map(item => item.id), ['wonder'])
  assert.deepEqual(service.imageStylesCatalog.value.map(item => item.id), ['style'])
  assert.equal(await service.removeItem('tones', 5), false)
})

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
