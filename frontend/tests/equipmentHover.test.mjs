import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { toRaw } from 'vue'
import ts from 'typescript'

const source = readFileSync(new URL('../src/composables/useEquipmentHover.ts', import.meta.url), 'utf8')
  .replace(/import[^\n]+from 'vue'/, `import {nextTick, ref} from '${import.meta.resolve('vue')}';
const onMounted = callback => globalThis.hoverTest.mount.push(callback);
const onBeforeUnmount = callback => globalThis.hoverTest.unmount.push(callback);`)
const code = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
const { useEquipmentHover } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)

function setup(t, width = 320, height = 844) {
  const prior = new Map(), listeners = new Map()
  const events = { addEventListener: (name, callback) => listeners.set(name, callback), removeEventListener: name => listeners.delete(name) }
  const dialog = {}, scrollBounds = { top: 80, bottom: 750 }
  const scrollParent = { parentElement: null, getBoundingClientRect: () => scrollBounds }
  const rect = { left: 140, right: 180, top: 300, bottom: 340, width: 40 }
  const anchor = { isConnected: true, parentElement: scrollParent, closest: () => dialog, contains: value => value === anchor, getBoundingClientRect: () => rect }
  for (const [key, value] of Object.entries({ hoverTest: { mount: [], unmount: [] }, window: events, document: { ...events, body: {} }, innerWidth: width, innerHeight: height, getComputedStyle: () => ({ overflowY: 'auto' }) })) {
    prior.set(key, Object.getOwnPropertyDescriptor(globalThis, key))
    Object.defineProperty(globalThis, key, { value, configurable: true, writable: true })
  }
  const hover = useEquipmentHover()
  const popupBounds = { width: 220, height: 140 }
  hover.popup.value = { getBoundingClientRect: () => popupBounds, contains: () => false }
  globalThis.hoverTest.mount.forEach(callback => callback())
  t.after(() => {
    globalThis.hoverTest.unmount.forEach(callback => callback())
    assert.equal(listeners.size, 0)
    for (const [key, descriptor] of prior) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor)
      else delete globalThis[key]
    }
  })
  return { hover, anchor, rect, popupBounds, listeners, dialog }
}

test('narrow-screen popovers remain within the viewport and do not cover the tapped slot', async t => {
  const { hover, anchor, rect, dialog } = setup(t)
  await hover.open('Chest', { currentTarget: anchor }, true)
  assert.equal(toRaw(hover.target.value), dialog)
  const x = parseFloat(hover.style.value.left), y = parseFloat(hover.style.value.top)
  assert(x >= 10 && x + 220 <= 310)
  assert(y >= rect.bottom + 10)
  assert.equal(hover.active.value, 'Chest')
})

test('bottom slots open above their anchor and close when it is clipped by the panel', async t => {
  const { hover, anchor, rect, listeners } = setup(t)
  Object.assign(rect, { top: 690, bottom: 730 })
  await hover.open('Feet', { currentTarget: anchor }, true)
  assert(parseFloat(hover.style.value.top) + 140 <= rect.top - 10)
  Object.assign(rect, { top: 30, bottom: 70 })
  listeners.get('scroll')()
  assert.equal(hover.active.value, '')
})

test('Escape closes the popup first; another Escape can reach the native dialog', async t => {
  const { hover, anchor, listeners } = setup(t, 1440, 1000)
  await hover.open('Chest', { currentTarget: anchor })
  let prevented = 0, stopped = 0
  const event = { key: 'Escape', preventDefault: () => prevented++, stopPropagation: () => stopped++ }
  listeners.get('keydown')(event)
  assert.equal(hover.active.value, '')
  listeners.get('keydown')(event)
  assert.equal(prevented, 1)
  assert.equal(stopped, 1)
})

test('scroll closes transient hover lists and outside taps close pinned lists', async t => {
  const { hover, anchor, listeners } = setup(t)
  await hover.open('Chest', { currentTarget: anchor })
  listeners.get('scroll')()
  assert.equal(hover.active.value, '')
  await hover.open('Chest', { currentTarget: anchor }, true)
  listeners.get('pointerdown')({ target: {} })
  assert.equal(hover.active.value, '')
})
