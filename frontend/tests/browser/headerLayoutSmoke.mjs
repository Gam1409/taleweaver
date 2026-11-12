import assert from 'node:assert/strict'
import process from 'node:process'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 320, height: 844 } })
const errors = []
page.on('pageerror', error => errors.push(error.message))
page.setDefaultTimeout(10000)
const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5203'
const session = () => page.getByRole('button', { name: 'Session', exact: true }).click()
const closeDetail = async () => {
  const settings = page.getByRole('button', { name: 'Close session settings', exact: true })
  if (await settings.count()) await settings.click()
  else await page.getByRole('button', { name: 'Close preview panel', exact: true }).click()
}
try {
  await page.goto(base + '/tests/browser/groupedActions.html?header-only=1')
  await page.locator('.game-header').waitFor()
  await page.evaluate(() => {
    window.groupedActionsFixture.setSpeech(true, true)
    window.groupedActionsFixture.setHeader({
      sceneName: 'The old observatory beyond the eastern mountains',
      adventureTitle: 'A journey to the lighthouse and the forgotten coast',
      activeSequence: { title: 'A long chapter about the lighthouse and the forgotten coast', description: 'The keeper left a note beside the lamp.', order: 3 },
      creator: 'Example Author', gameTime: { dateShort: 'The fourth watch', time: '42 bells', isUnits: true },
    })
  })
  const metrics = await page.locator('.header-metrics').boundingBox()
  const controls = await page.locator('.game-header-controls').boundingBox()
  assert.ok(metrics.x + metrics.width <= controls.x, 'Time/XP must not overlap the stop, language or session controls at 320px.')
  await page.getByRole('button', { name: 'Stop speech', exact: true }).click()
  await page.getByRole('button', { name: 'Stop speech', exact: true }).waitFor({ state: 'hidden' })
  await page.locator('.header-chapter-trigger').focus()
  await page.keyboard.press('Enter')
  await page.getByText('The keeper left a note beside the lamp.', { exact: true }).waitFor()
  const chapter = await page.locator('.header-chapter-details').boundingBox()
  assert.ok(chapter.x >= 0 && chapter.x + chapter.width <= 320)
  await page.keyboard.press('Escape')
  await page.locator('.header-chapter-details').waitFor({ state: 'hidden' })
  await page.evaluate(() => window.groupedActionsFixture.setHeader({
    adventureTitle: 'Coast', activeSequence: { title: 'Chapter 1', description: 'A note beside the lamp.' },
  }))
  for (const width of [320, 390, 640]) {
    await page.setViewportSize({ width, height: 844 })
    await page.locator('.header-chapter-trigger').click()
    const shortChapter = await page.locator('.header-chapter-details').boundingBox()
    assert.ok(shortChapter.x >= 12 && shortChapter.x + shortChapter.width <= width - 12,
      `Short chapter metadata must keep the popup within the ${width}px viewport.`)
    await page.keyboard.press('Escape')
  }
  const zoom = await page.context().newCDPSession(page)
  await page.setViewportSize({ width: 844, height: 320 })
  for (const scale of [2, 3]) {
    await zoom.send('Emulation.setPageScaleFactor', { pageScaleFactor: scale })
    for (const control of [page.locator('.header-chapter-trigger'), page.getByRole('button', { name: 'Session', exact: true })]) {
      await control.focus()
      await page.keyboard.press('Enter')
      await page.waitForTimeout(250)
      const visible = await page.evaluate(() => {
        const panel = document.querySelector('.header-chapter-details, [role="menu"]:not([inert])').getBoundingClientRect()
        const viewport = visualViewport
        return { left: panel.left, right: panel.right, top: panel.top, bottom: panel.bottom,
          x: viewport.offsetLeft, y: viewport.offsetTop, width: viewport.width, height: viewport.height }
      })
      assert.ok(visible.left >= visible.x + 11 && visible.right <= visible.x + visible.width - 11 &&
        visible.top >= visible.y + 11 && visible.bottom <= visible.y + visible.height - 11,
      `Header popup must fit the short visible viewport at ${scale}x zoom: ${JSON.stringify(visible)}`)
      await page.keyboard.press('Escape')
    }
    await zoom.send('Emulation.setPageScaleFactor', { pageScaleFactor: 1 })
  }
  await zoom.detach()
  await page.setViewportSize({ width: 320, height: 844 })
  await page.locator('.header-quest').focus()
  await page.keyboard.press('Enter')
  await page.getByRole('heading', { name: 'Quests', exact: true }).waitFor()
  await closeDetail()
  for (const name of ['Session settings', 'Chronicles', 'Debug inspector', 'Exit session']) {
    await session()
    await page.getByRole('menu', { name: 'Session', exact: true }).getByRole('menuitem', { name: new RegExp('^' + name) }).click()
    await page.getByRole('heading', { name, exact: true }).waitFor()
    await closeDetail()
  }
  await session()
  await page.getByRole('menuitem', { name: /^Auto-narration off/ }).click()
  await session()
  await page.getByRole('menuitem', { name: /^Auto-narration on/ }).waitFor()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Open Bable Fish translation', exact: true }).click()
  await page.getByRole('button', { name: 'Русский', exact: true }).click()
  await page.getByRole('button', { name: 'Translation active: Русский', exact: true }).waitFor()
  await page.evaluate(() => window.groupedActionsFixture.setBusy(true))
  assert.equal(await page.getByRole('button', { name: 'Translation active: Русский', exact: true }).isDisabled(), true)
  await page.evaluate(() => {
    window.groupedActionsFixture.setBusy(false)
    window.groupedActionsFixture.setDebug(false)
    window.groupedActionsFixture.setMode('vn')
    window.groupedActionsFixture.setSpeech(false)
  })
  assert.equal(await page.locator('.header-quest').count(), 0)
  assert.equal(await page.locator('.header-experience').count(), 0)
  await page.getByText('42 bells', { exact: true }).waitFor()
  await session()
  assert.equal(await page.getByRole('menuitem', { name: /^Debug inspector/ }).count(), 0)
  assert.equal(await page.getByRole('menuitem', { name: /^Auto-narration/ }).count(), 0)
  await page.keyboard.press('Escape')
  await page.evaluate(() => {
    window.groupedActionsFixture.setHeader({ systemDebugEnabled: true })
    window.groupedActionsFixture.setBehavior({ module_version: '4.0', mode: 'live', quality: 'partial', reason: '', cooldown_remaining: 2, unreviewed_turns: 1, total_simplified_turns: 0 })
  })
  await page.getByLabel('Session UUID', { exact: true }).waitFor()
  await page.getByRole('status', { name: /Some NPCs have no confirmed decision/ }).waitFor()
  await page.evaluate(() => window.groupedActionsFixture.setHeader({ gameTime: null }))
  assert.equal(await page.locator('.header-metrics').count(), 0)
  for (const width of [320, 390, 768, 900, 1440]) {
    await page.setViewportSize({ width, height: 1000 })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
    await session()
    const bounds = await page.getByRole('menu', { name: 'Session', exact: true }).boundingBox()
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width + 1)
    assert.ok(bounds.y >= 0 && bounds.y + bounds.height <= 1000)
    await page.keyboard.press('Escape')
  }
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.evaluate(() => window.groupedActionsFixture.setHeader({ clockTick: true, gameTime: { dateShort: 'Day 3', time: '18:42' } }))
  assert.ok(parseFloat(await page.locator('.clock-time').evaluate(el => getComputedStyle(el).animationDuration)) < .01)
  await page.goto(base + '/tests/browser/groupedActions.html')
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 })
    await page.waitForTimeout(100)
    await page.screenshot({ path: `/tmp/taleweaver-header-preview-${width}.png` })
    await page.locator('.game-header').screenshot({ path: `/tmp/taleweaver-header-bar-${width}.png` })
  }
  assert.deepEqual(errors, [])
  console.log('Header: no overlap with full speech controls, chapter keyboard details, quests, settings, history, debug, exit, speech gates, language, VN/custom clock, diagnostics, five viewport sizes and reduced motion passed.')
} finally {
  await browser.close()
}
