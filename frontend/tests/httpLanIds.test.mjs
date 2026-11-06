import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { webcrypto } from 'node:crypto'
import ts from 'typescript'
import { uuidModule } from './uuidModule.mjs'

const { createUuid } = await import(uuidModule)
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

function useCrypto(t, value) {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'crypto')
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value })
  t.after(() => {
    if (descriptor) Object.defineProperty(globalThis, 'crypto', descriptor)
    else delete globalThis.crypto
  })
}

test('secure origins use the native UUID implementation', t => {
  let calls = 0
  useCrypto(t, {
    randomUUID: () => {
      calls++
      return 'native-id'
    }
  })
  assert.equal(createUuid(), 'native-id')
  assert.equal(calls, 1)
})

for (const cryptoApi of [
  { getRandomValues: webcrypto.getRandomValues.bind(webcrypto) },
  undefined
]) {
  test(`UUID fallback works ${cryptoApi ? 'on HTTP LAN' : 'without Web Crypto'}`, t => {
    useCrypto(t, cryptoApi)
    const ids = Array.from({ length: 1000 }, createUuid)
    assert.equal(new Set(ids).size, ids.length)
    for (const id of ids) assert.match(id, uuidPattern)
  })
}

// Execute the actual six ID expressions, including both IDs in each creation UI.
const files = [
  'services/visualJobs.ts',
  'services/catalogService.ts',
  'views/CreateAdventureView.vue',
  'components/game/AdventureGeneratorModal.vue'
]
for (const file of files) {
  const text = readFileSync(new URL(`../src/${file}`, import.meta.url), 'utf8')
  const script = file.endsWith('.vue')
    ? text.match(/<script setup[^>]*>([\s\S]*?)<\/script>/)[1]
    : text
  const tree = ts.createSourceFile(file, script, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
  const expressions = []
  const visit = node => {
    if (
      ts.isCallExpression(node) &&
      /^(crypto\.randomUUID|createUuid)$/.test(node.expression.getText(tree))
    ) {
      expressions.push(node.getText(tree))
    }
    ts.forEachChild(node, visit)
  }
  visit(tree)
  test(`${file} covers all expected ID allocations`, () => {
    assert.equal(expressions.length, file.endsWith('.vue') ? 2 : 1)
  })
  expressions.forEach((expression, index) => {
    test(`${file} ID ${index + 1} works without randomUUID`, t => {
      const cryptoApi = { getRandomValues: webcrypto.getRandomValues.bind(webcrypto) }
      useCrypto(t, cryptoApi)
      const id = new Function('createUuid', 'crypto', `return ${expression}`)(createUuid, cryptoApi)
      assert.match(id, uuidPattern)
    })
  })
}
