import assert from 'node:assert/strict'
import process from 'node:process'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1380, height: 900 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
page.setDefaultTimeout(15000)
const adventure = { id: 'scroll-adventure', title: 'A crowded wardrobe', status: 'ready', rule_enforcement_mode: 'vn', start_scene_id: 'LAB' }
const items = Array.from({ length: 144 }, (_, i) => ({ id: `ITEM_${i}`, name: `Item ${String(i + 1).padStart(3, '0')}`,
  description: 'A carefully made inventory object.', entity_type: 'OBJECT', item_type: 'DEFAULT', current_scene_id: 'LAB' }))
try {
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname
    const data = path.endsWith('/editor/assets') ? { adventure, objects: items, scenes: [{ id: 'LAB', label: 'Laboratory', name: 'Laboratory' }], npcs: [], entities_all: [] }
      : path === '/api/adventures/scroll-adventure' ? adventure
      : path.endsWith('/world-brief') ? { setting: '', history: '', opening: '', characters: '', world_rules: '', open_threads: '', references: [] }
      : { image_styles_catalog: [], tone_catalog: [], tts_settings: {} }
    await route.fulfill({ json: data })
  })
  for (const viewport of [{ width: 1380, height: 900 }, { width: 390, height: 700 }, { width: 812, height: 320 }]) {
    await page.setViewportSize(viewport)
    await page.goto((process.env.FRONTEND_URL || 'http://127.0.0.1:5206') + '/tests/browser/editorItemsScroll.html')
    await page.getByRole('button', { name: 'Items', exact: true }).filter({ visible: true }).click()
    await page.getByText('Item 144', { exact: true }).waitFor({ state: 'attached' })
    const scroll = page.locator('#route-viewport > div')
    const dimensions = await scroll.evaluate(element => {
      const box = element.getBoundingClientRect()
      return { top: box.top, bottom: box.bottom, height: element.clientHeight, content: element.scrollHeight }
    })
    assert.ok(dimensions.bottom <= viewport.height + 1, `Editor exceeds the usable viewport: ${JSON.stringify(dimensions)}`)
    assert.ok(dimensions.content > dimensions.height)
    await page.mouse.move(viewport.width - 50, viewport.height - 120)
    await page.mouse.wheel(0, 1200)
    await page.waitForFunction(() => document.querySelector('#route-viewport > div').scrollTop > 0)
    await scroll.focus()
    await page.keyboard.press('Control+End')
    await page.waitForFunction(() => {
      const element = document.querySelector('#route-viewport > div')
      return element.scrollTop + element.clientHeight >= element.scrollHeight - 2
    })
    const last = await scroll.getByText('Item 144', { exact: true }).boundingBox()
    assert.ok(last.y + last.height <= viewport.height, `Last item is clipped: ${JSON.stringify(last)}`)
    const trigger = page.getByRole('button', { name: 'Actions for Item 144', exact: true })
    await trigger.click()
    const menu = page.getByRole('group', { name: 'Item 144 actions', exact: true })
    await menu.waitFor({ state: 'visible' })
    const box = await menu.boundingBox()
    assert.ok(box.x >= 0 && box.x + box.width <= viewport.width, `Menu escapes horizontally: ${JSON.stringify(box)}`)
    assert.ok(box.y >= 0 && box.y + box.height <= viewport.height, `Menu escapes vertically: ${JSON.stringify(box)}`)
    assert.equal(await menu.evaluate(element => element.parentElement === document.body), true)
    await menu.getByRole('button', { name: 'Delete', exact: true }).scrollIntoViewIfNeeded()
    const deleteBox = await menu.getByRole('button', { name: 'Delete', exact: true }).boundingBox()
    assert.ok(deleteBox.y >= 0 && deleteBox.y + deleteBox.height <= viewport.height)
    if (viewport.width === 1380) await page.screenshot({ path: '/tmp/editor-items-menu-fixed.png' })
    await page.keyboard.press('Escape')
    await menu.waitFor({ state: 'hidden' })
    assert.equal(await trigger.evaluate(element => element === document.activeElement), true)
    await trigger.click()
    await menu.waitFor({ state: 'visible' })
    await page.mouse.click(2, 2)
    await menu.waitFor({ state: 'hidden' })
    await trigger.click()
    await menu.waitFor({ state: 'visible' })
    await scroll.focus()
    await page.keyboard.press('Control+Home')
    await menu.waitFor({ state: 'hidden' })
    await page.getByRole('button', { name: 'Add', exact: true }).waitFor({ state: 'visible' })
  }
  assert.deepEqual(errors, [])
  console.log('Items browser checks passed: 144 items, desktop/mobile/short viewport, wheel and keyboard scrolling, last row, bounded menus, scrollable Delete, Escape focus and outside click.')
} catch (error) {
  console.error('Browser errors:', errors)
  console.error('Visible content:', (await page.locator('body').innerText()).slice(0, 1200))
  await page.screenshot({ path: '/tmp/editor-items-scroll-failure.png', fullPage: true })
  throw error
} finally {
  await browser.close()
}
