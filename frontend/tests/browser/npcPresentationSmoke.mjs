import assert from 'node:assert/strict'
import process from 'node:process'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium',
  headless: true,
  args: ['--no-sandbox']
})
const page = await browser.newPage({
  viewport: { width: 1200, height: 900 },
  reducedMotion: 'reduce'
})
const errors = []
const calls = []
const off = { emotion_palette: false, character_thoughts: false, brightness: 40 }
page.on('pageerror', error => errors.push(error.message))
await page.route('**/api/**', async route => {
  calls.push(route.request().method())
  const card = {
    id: 'RIN',
    name: 'Dr. Rin',
    description: 'A resolute physician.',
    entries: [],
    summary: [],
    aliases: [],
    entry_count: 0,
    history_counts: { general: 0, shared: 0 }
  }
  await route.fulfill({
    json: route.request().url().includes('/npcs/')
      ? card
      : route.request().method() === 'PATCH'
        ? route.request().postDataJSON().settings
        : off
  })
})
try {
  await page.goto(
    (process.env.FRONTEND_URL || 'http://127.0.0.1:5193') + '/tests/browser/npcPresentation.html'
  )
  const rin = page.locator('[tabindex="0"]').filter({ hasText: 'Dr. Rin' })
  const hoverPortrait = async () => {
    await rin.scrollIntoViewIfNeeded()
    // Finish fixture-page scrolling before hover; scrolling intentionally dismisses thoughts.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    await rin.hover()
  }
  await rin.waitFor()
  await page.getByRole('button', { name: 'Move player here', exact: true }).click()
  assert.equal(
    await page.locator('#manual-player-move').textContent(),
    '/debug move_player "RESEARCH_LAB"'
  )
  assert.equal(await page.getByText(/Works without NPC Personality/).count(), 1)
  assert.equal(await page.getByText('Item and travel checks').count(), 0)
  assert.match(await rin.getAttribute('style'), /12,\s*10,\s*18/)
  await hoverPortrait()
  const bubble = page.getByRole('tooltip')
  await bubble.waitFor({ state: 'visible' })
  assert.equal(
    await bubble.locator('p').evaluate(element => getComputedStyle(element).fontStyle),
    'normal',
    'thought text should stay readable without a forced italic face'
  )
  assert.equal(
    await bubble.evaluate(element => element.getAnimations({ subtree: true }).length),
    0,
    'reduced-motion mode must not animate the thought'
  )
  assert.equal(await bubble.locator('script').count(), 0)
  assert.match(await bubble.textContent(), /<script>stay calm<\/script>/)
  assert.equal(calls.length, 1, 'hover must not send any model/API requests')
  await page.keyboard.press('Escape')
  await bubble.waitFor({ state: 'hidden' })
  await rin.focus()
  await bubble.waitFor({ state: 'visible' })
  await rin.press('Enter')
  await page.getByRole('dialog').waitFor({ state: 'visible' })
  assert.equal(
    await page.locator('#portrait-clicks').textContent(),
    '0',
    'portrait click opens the character card, not a story action'
  )
  assert.equal(
    await page.locator('#legacy-hovers').textContent(),
    '0',
    'thought hover must suppress the previous card tooltip'
  )
  await page.getByRole('button', { name: 'Close character', exact: true }).click()
  await rin.click()
  await page.getByRole('dialog').waitFor({ state: 'visible' })
  await page.getByRole('button', { name: 'Close character', exact: true }).click()
  await page.locator('[tabindex="0"]').filter({ hasText: 'Unassessed NPC' }).hover()
  await bubble.waitFor({ state: 'hidden' })
  assert.equal(
    await page.locator('#legacy-hovers').textContent(),
    '0',
    'unassessed NPC must not fall back to the old hover card'
  )
  await page.getByText('Thoughts only', { exact: true }).click()
  assert.doesNotMatch((await rin.getAttribute('style')) || '', /12,\s*10,\s*18/)
  await hoverPortrait()
  await bubble.waitFor({ state: 'visible' })
  await page.getByText('Disable effects', { exact: true }).click()
  await hoverPortrait()
  await bubble.waitFor({ state: 'hidden' })
  await page.getByLabel('Мысли персонажей', { exact: true }).check()
  await Promise.all([
    page.waitForResponse('**/portrait-settings'),
    page.getByRole('button', { name: 'Save presentation' }).click()
  ])
  assert.ok(calls.includes('PATCH'))
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByText('Thoughts only', { exact: true }).click()
  await rin.focus()
  await bubble.waitFor({ state: 'visible' })
  const bounds = await bubble.boundingBox()
  assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 390)
  assert.ok(bounds.y >= 0 && bounds.y + bounds.height <= 844)
  await page.keyboard.press('Escape')
  await bubble.waitFor({ state: 'hidden' })
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  const beforeAnimation = calls.length
  await hoverPortrait()
  await bubble.waitFor({ state: 'visible' })
  assert.ok(
    await bubble.evaluate(element =>
      element
        .getAnimations({ subtree: true })
        .some(animation => Number(animation.effect?.getTiming().duration) >= 200)
    ),
    'the cloud should animate on arrival'
  )
  await page.waitForFunction(() => {
    const element = document.querySelector('#npc-current-thought')
    return (
      element &&
      getComputedStyle(element).opacity === '1' &&
      element.getAnimations({ subtree: true }).length === 0
    )
  })
  const settled = await bubble.boundingBox()
  assert.ok(settled.x >= 0 && settled.x + settled.width <= 390)
  assert.ok(settled.y >= 0 && settled.y + settled.height <= 844)
  assert.equal(
    calls.length,
    beforeAnimation,
    'opening an animated thought must not make API requests'
  )
  for (const width of [1200, 390]) {
    await page.setViewportSize({ width, height: 900 })
    await page.evaluate(() => window.npcPresentationFixture.setCustomColor('<em>uncertain</em>'))
    await page.waitForFunction(() => document.querySelector('.emotion-portrait').getAttribute('aria-label').includes('<em>uncertain</em>'))
    assert.match(await rin.getAttribute('style'), /140,\s*160,\s*210/)
    assert.equal(await rin.locator('em').count(), 0, 'feeling labels remain escaped text')
    await page.evaluate(() => window.npcPresentationFixture.clearAssessment())
    await page.waitForFunction(() => !document.querySelector('.emotion-portrait').getAttribute('aria-label').includes('uncertain'))
    assert.doesNotMatch((await rin.getAttribute('style')) || '', /140,\s*160,\s*210/)
    await page.evaluate(() => window.npcPresentationFixture.setCustomColor())
    await page.getByText('Disable effects', { exact: true }).click()
    assert.doesNotMatch((await rin.getAttribute('style')) || '', /140,\s*160,\s*210/)
  }
  assert.equal(calls.length, beforeAnimation, 'changing local presentation must not call the API')
  assert.equal(errors.length, 0, errors.join('\n'))
  console.log('Portrait presentation browser checks passed.')
} finally {
  await browser.close()
}
