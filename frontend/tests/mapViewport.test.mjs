import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRenderer, h, ref } from 'vue'
import ts from 'typescript'

const source = readFileSync(new URL('../src/composables/useMapViewport.ts', import.meta.url), 'utf8')
const code = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  .replace("from 'vue'", `from '${import.meta.resolve('vue')}'`)
const { useMapViewport } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
const renderer = createRenderer({ createElement: type => ({ type, children: [] }), createText: text => ({ text }), createComment: text => ({ text }), setText() {}, setElementText() {}, patchProp() {}, insert(node, parent) { parent.children.push(node) }, remove() {}, parentNode: () => null, nextSibling: () => null })
const event = (pointerId, x = 0, y = 0, extras = {}) => ({ pointerId, clientX: x, clientY: y, button: 0, ...extras })
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-8, `${actual} differs from ${expected}`)
function fixture(t, initialZoom = 1, initialOffset = { x: 0, y: 0 }) {
  const originalWindow = globalThis.window
  const window = new EventTarget(), captures = new Set(), released = []
  globalThis.window = window
  const zoom = ref(initialZoom), offset = ref(initialOffset), origin = { x: 640, y: 450 }
  const viewport = ref({ setPointerCapture: id => captures.add(id), hasPointerCapture: id => captures.has(id), releasePointerCapture(id) { released.push(id); captures.delete(id) } })
  const content = ref({ getBoundingClientRect: () => ({ left: origin.x + offset.value.x - 120 * zoom.value, top: origin.y + offset.value.y - 80 * zoom.value, width: 240 * zoom.value, height: 160 * zoom.value }) })
  let gestures
  const app = renderer.createApp({ setup() { gestures = useMapViewport(viewport, content, zoom, offset); return () => h('div') } })
  app.mount({ children: [] })
  t.after(() => { app.unmount(); globalThis.window = originalWindow })
  const point = (x, y) => ({ x: origin.x + offset.value.x + x * zoom.value, y: origin.y + offset.value.y + y * zoom.value })
  const begin = center => { gestures.handlePointerDown(event(1, center.x - 40, center.y)); gestures.handlePointerDown(event(2, center.x + 40, center.y)) }
  const pinch = (center, distance) => { gestures.handlePointerMove(event(1, center.x - distance / 2, center.y)); gestures.handlePointerMove(event(2, center.x + distance / 2, center.y)) }
  return { ...gestures, app, window, captures, released, zoom, offset, point, begin, pinch }
}

for (const [zoom, offset] of [[1, { x: 0, y: 0 }], [1.7, { x: 123, y: -37 }]]) test(`pinch at ${zoom} preserves the touched content with existing pan`, t => {
  const f = fixture(t, zoom, offset), anchor = f.point(45, -25)
  f.begin(anchor); f.pinch(anchor, 120)
  close(f.zoom.value, zoom * 1.5)
  close(f.point(45, -25).x, anchor.x); close(f.point(45, -25).y, anchor.y)
})
test('moving the pinch midpoint moves the same touched content by that amount', t => {
  const f = fixture(t, 1.2, { x: -50, y: 72 }), anchor = f.point(-30, 40)
  f.begin(anchor); f.pinch({ x: anchor.x + 25, y: anchor.y - 15 }, 120)
  close(f.point(-30, 40).x, anchor.x + 25); close(f.point(-30, 40).y, anchor.y - 15)
})
for (const [initial, distance, expected] of [[2.5, 800, 3], [0.3, 8, 0.2]]) test(`pinch clamps at ${expected} without moving its anchor`, t => {
  const f = fixture(t, initial, { x: 21, y: 13 }), anchor = f.point(50, 30)
  f.begin(anchor); f.pinch(anchor, distance)
  close(f.zoom.value, expected); close(f.point(50, 30).x, anchor.x); close(f.point(50, 30).y, anchor.y)
})
test('pinch falls back to pan without a jump when one pointer ends', t => {
  const f = fixture(t), anchor = f.point(0, 0)
  f.begin(anchor); f.pinch(anchor, 120)
  f.handlePointerUp(event(1))
  const before = { ...f.offset.value }
  f.handlePointerMove(event(2, anchor.x + 70, anchor.y + 8))
  close(f.offset.value.x, before.x + 10); close(f.offset.value.y, before.y + 8)
  assert.deepEqual([...f.captures], [2])
})
test('three pointers rebase the two remaining pointers rather than jumping', t => {
  const f = fixture(t), anchor = f.point(0, 0)
  f.begin(anchor)
  f.handlePointerDown(event(3, anchor.x, anchor.y + 50))
  f.handlePointerMove(event(1, anchor.x - 80, anchor.y))
  f.handlePointerUp(event(3))
  const before = { ...f.offset.value }, beforeZoom = f.zoom.value
  f.handlePointerMove(event(2, anchor.x + 40, anchor.y))
  close(f.zoom.value, beforeZoom); close(f.offset.value.x, before.x); close(f.offset.value.y, before.y)
})
for (const reason of ['reset', 'blur', 'unmount']) test(`${reason} releases all pointer captures and ignores old movements`, t => {
  const f = fixture(t), anchor = f.point(0, 0)
  f.begin(anchor)
  if (reason === 'reset') f.resetPointers()
  if (reason === 'blur') f.window.dispatchEvent(new Event('blur'))
  if (reason === 'unmount') f.app.unmount()
  f.handlePointerMove(event(1, 10, 10))
  assert.deepEqual(f.offset.value, { x: 0, y: 0 }); assert.equal(f.captures.size, 0)
  assert.deepEqual(f.released.sort(), [1, 2])
})
test('mouse pan and wheel preserve their existing direction and bounds', t => {
  const f = fixture(t)
  f.handlePointerDown(event(1, 100, 100, { pointerType: 'mouse' }))
  f.handlePointerMove(event(1, 120, 85)); f.handlePointerUp(event(1))
  assert.deepEqual(f.offset.value, { x: 20, y: -15 })
  let prevented = 0
  f.handleWheel({ deltaY: -1, preventDefault() { prevented++ } })
  close(f.zoom.value, 1.1); assert.equal(prevented, 1)
})
