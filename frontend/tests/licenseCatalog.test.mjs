import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import ts from 'typescript'

const source = readFileSync(new URL('../src/utils/licenseCatalog.ts', import.meta.url), 'utf8')
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText
const { LICENSE_CATALOG } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
const readPublic = path => readFileSync(new URL('../public' + path, import.meta.url), 'utf8')

test('application and sample license texts preserve complete upstream notices', () => {
  assert.equal(readPublic(LICENSE_CATALOG.find(item => item.id === 'application').url), readFileSync(new URL('../../LICENSE', import.meta.url), 'utf8'))
  assert.equal(readPublic(LICENSE_CATALOG.find(item => item.id === 'samples').url), readFileSync(new URL('../../LICENSE-CC-BY-NC-4.0', import.meta.url), 'utf8'))
})

test('every license has a unique local document with its recorded full-text checksum', () => {
  const records = JSON.parse(readPublic('/assets/licenses/sources.json'))
  assert.equal(new Set(LICENSE_CATALOG.map(item => item.id)).size, LICENSE_CATALOG.length)
  assert.equal(records.length, LICENSE_CATALOG.length)
  for (const item of LICENSE_CATALOG) {
    assert.match(item.url, /^\/assets\/(?:fonts|licenses)\//)
    assert.doesNotMatch(item.url, /\.\./)
    const text = readPublic(item.url)
    assert.ok(text.length > 200, item.id)
    assert.equal(createHash('sha256').update(text).digest('hex'), records.find(record => record.id === item.id)?.sha256, item.id)
  }
})
