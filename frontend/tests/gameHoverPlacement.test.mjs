import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import ts from 'typescript'

const source = ts.transpileModule(readFileSync(new URL('../src/utils/gameHoverPlacement.ts', import.meta.url), 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
const { gameHoverPlacement } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`)

test('details fit visible portrait, landscape and zoomed frames without covering a compact source', () => {
  for (const viewport of [
    { left: 0, top: 0, width: 320, height: 568, layoutHeight: 568 },
    { left: 0, top: 0, width: 390, height: 844, layoutHeight: 844 },
    { left: 0, top: 0, width: 1440, height: 1000, layoutHeight: 1000 },
    { left: 0, top: 0, width: 800, height: 420, layoutHeight: 420 },
    { left: 195, top: 100, width: 195, height: 422, layoutHeight: 844 },
  ]) {
    for (const rightEdge of [false, true]) {
      const left = viewport.left + (rightEdge ? viewport.width - 68 : 24)
      const anchor = { left, right: left + 44, top: viewport.top + 30, bottom: viewport.top + 74 }
      const value = gameHoverPlacement({ x: left + 22, y: anchor.top + 22 }, viewport, anchor)
      const width = parseFloat(value.width), height = parseFloat(value.maxHeight)
      const x = parseFloat(value.left), y = value.top === 'auto' ? viewport.layoutHeight - parseFloat(value.bottom) - height : parseFloat(value.top)
      assert.ok(x >= viewport.left && x + width <= viewport.left + viewport.width)
      assert.ok(y >= viewport.top && y + height <= viewport.top + viewport.height)
      assert.ok(x + width <= anchor.left || x >= anchor.right || y + height <= anchor.top || y >= anchor.bottom)
    }
  }
})

test('a partially clipped oversized source still leaves a readable region away from the pointer', () => {
  const viewport = { left: 0, top: 0, width: 320, height: 240, layoutHeight: 240 }
  const value = gameHoverPlacement({ x: 150, y: 80 }, viewport, { left: 0, right: 320, top: -100, bottom: 400 })
  assert.ok(parseFloat(value.maxHeight) > 100)
  assert.ok(parseFloat(value.top) > 80)
  assert.ok(parseFloat(value.top) + parseFloat(value.maxHeight) <= 240)
})
