import assert from 'node:assert/strict'
import process from 'node:process'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, reducedMotion: 'reduce' })
const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5203'
const errors = []
page.on('pageerror', error => errors.push(error.message))
await page.route('**/api/**', route => route.fulfill({ json: { emotion_palette: true, character_thoughts: true, brightness: 100 } }))
async function spacing(emotion, vertical) {
  const layout = await page.locator('.game-character-stage').evaluate(stage => {
    const strip = stage.firstElementChild, cards = [...strip.children].filter(node => node.classList.contains('emotion-portrait'))
    const boxes = cards.map(card => card.getBoundingClientRect()), outer = stage.getBoundingClientRect(), inner = strip.getBoundingClientRect(), style = getComputedStyle(strip)
    return { gap: verticalGap(boxes), paddingTop: parseFloat(style.paddingTop), paddingBottom: parseFloat(style.paddingBottom), stageHeight: outer.height, innerHeight: inner.height, firstInset: boxes[0].top - outer.top, rowGap: boxes[1].left - boxes[0].right }
    function verticalGap(boxes) { return boxes[1].top - boxes[0].bottom }
  })
  assert.ok(layout.paddingTop >= (emotion ? 24 : 16), 'Reserve glow space above the first portrait.')
  assert.ok(layout.paddingBottom >= (emotion ? 24 : 16), 'Reserve glow space below the last portrait.')
  assert.ok((vertical ? layout.gap : layout.rowGap) >= (emotion ? 48 : 32), 'Adjacent portrait halos need their own space.')
  if (!vertical) assert.ok(layout.stageHeight >= layout.innerHeight - 1, 'The mobile scrollport must not crop top/bottom glow padding.')
}
try {
  await page.goto(base + '/tests/browser/npcPresentation.html')
  await page.locator('.emotion-portrait').first().waitFor()
  await page.evaluate(() => window.npcPresentationFixture.setMaximum())
  await spacing(true, true)
  await page.getByText('Disable effects', { exact: true }).click()
  await spacing(false, true)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => window.npcPresentationFixture.setMaximum())
  await spacing(true, false)
  await page.getByText('Disable effects', { exact: true }).click()
  await spacing(false, false)
  assert.deepEqual(errors, [])
  console.log('Portrait spacing: vertical/horizontal cards, maximum emotion brightness, fallback speaker halos and outer padding passed.')
} finally { await browser.close() }
