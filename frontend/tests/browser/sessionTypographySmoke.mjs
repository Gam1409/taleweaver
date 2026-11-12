import assert from 'node:assert/strict'
import process from 'node:process'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' })
page.setDefaultTimeout(15000)
const errors = [], fontRequests = [], failedFonts = []
page.on('pageerror', error => errors.push(error.message))
page.on('request', request => { if (/\.woff2/.test(request.url())) fontRequests.push(request.url()) })
page.on('response', response => { if (/\.woff2/.test(response.url()) && ![200, 304].includes(response.status())) failedFonts.push(response.url()) })
const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5203'
const choose = async name => {
  await page.locator('.bable-fish-container > button').click()
  await page.locator('[data-bable-fish-dropdown]').getByRole('button', { name, exact: true }).click()
}
try {
  await page.goto(base + '/tests/browser/groupedActions.html?mode=vn')
  const session = await page.context().newCDPSession(page)
  await session.send('DOM.enable'); await session.send('CSS.enable')
  for (const [name, family, slug, direction, samplePrefix] of [
    ['Русский', 'Alegreya Sans', 'alegreya-sans', 'ltr', 'Вечерний свет'], ['العربية', 'Baloo Bhaijaan 2', 'baloo-bhaijaan-2', 'rtl', 'ينساب ضوء'],
    ['日本語', 'M PLUS Rounded 1c', 'm-plus-rounded-1c', 'ltr', '夕暮れ'], ['简体中文', 'Noto Sans SC', 'noto-sans-sc', 'ltr', '傍晚的光落在档案室'],
    ['繁體中文', 'Noto Sans TC', 'noto-sans-tc', 'ltr', '傍晚的光落在檔案室'], ['한국어', 'Noto Sans KR', 'noto-sans-kr', 'ltr', '저녁 햇살']
  ]) {
    await choose(name)
    await page.waitForFunction(family => document.documentElement.dataset.sessionFont === family, family)
    await page.getByRole('button', { name: 'Sample reply', exact: true }).click()
    await page.waitForFunction(prefix => [...document.querySelectorAll('.comic-narration-text')].at(-1)?.textContent.includes(prefix), samplePrefix)
    const text = page.locator('.comic-narration-text').last()
    await page.locator('#typography-sample').evaluateAll(nodes => nodes.forEach(node => node.removeAttribute('id')))
    await text.evaluate(node => { node.id = 'typography-sample' })
    await page.evaluate(async () => { await new Promise(resolve => setTimeout(resolve, 100)); await document.fonts.ready })
    assert.match(await text.evaluate(node => getComputedStyle(node).fontFamily), new RegExp(family.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
    assert.equal(await text.getAttribute('dir'), direction)
    const { root } = await session.send('DOM.getDocument')
    const { nodeId } = await session.send('DOM.querySelector', { nodeId: root.nodeId, selector: '#typography-sample > span:last-child' })
    const actual = await session.send('CSS.getPlatformFontsForNode', { nodeId })
    assert.ok(actual.fonts.every(font => font.isCustomFont), JSON.stringify(actual.fonts))
    console.log(family + ': ' + actual.fonts.map(font => font.familyName).join(', '))
    assert.ok(fontRequests.some(url => url.includes('/' + slug + '/')), family + ' must use local font files')
    await page.screenshot({ path: `/tmp/taleweaver-font-${slug}.png` })
  }
  for (const [name, family] of [['Русский', 'Alegreya Sans'], ['العربية', 'Baloo Bhaijaan 2']]) {
    await choose(name)
    await page.waitForFunction(family => document.documentElement.dataset.sessionFont === family, family)
    await page.getByRole('button', { name: 'Session', exact: true }).click()
    await page.getByRole('menuitem', { name: /Session settings/ }).click()
    const settings = page.getByRole('dialog', { name: 'Session settings', exact: true })
    await settings.waitFor()
    assert.equal(await settings.evaluate(node => node.parentElement.parentElement === document.body), true, 'Settings must exercise the teleported dialog.')
    for (const element of [settings, settings.locator('#session-settings-title')]) {
      assert.ok((await element.evaluate(node => getComputedStyle(node).fontFamily)).startsWith(`"${family}"`), `${family} must reach the settings frame and heading`)
    }
    await settings.getByRole('tab', { name: /Memory & audio/ }).click()
    const turns = settings.getByLabel('Narrator Turn Memory', { exact: true })
    assert.ok((await turns.evaluate(node => getComputedStyle(node).fontFamily)).startsWith(`"${family}"`), `${family} must reach numeric memory controls`)
    await page.evaluate(() => document.fonts.ready)
    const { root } = await session.send('DOM.getDocument')
    const { nodeId } = await session.send('DOM.querySelector', { nodeId: root.nodeId, selector: '#session-settings-title' })
    const actual = await session.send('CSS.getPlatformFontsForNode', { nodeId })
    assert.ok(actual.fonts.length > 0 && actual.fonts.every(font => font.isCustomFont && font.familyName === family), JSON.stringify(actual.fonts))
    await settings.getByRole('button', { name: 'Close session settings', exact: true }).click()
  }
  await choose('Русский')
  await page.evaluate(() => window.groupedActionsFixture.failLanguageSave(true))
  await choose('العربية')
  assert.equal(await page.evaluate(() => document.documentElement.dataset.sessionFont), 'Alegreya Sans')
  await page.keyboard.press('Escape')
  await page.evaluate(() => window.groupedActionsFixture.failLanguageSave(false))
  await page.setViewportSize({ width: 320, height: 640 })
  await choose('한국어')
  await page.locator('.bable-fish-container > button').click()
  const dropdown = await page.locator('[data-bable-fish-dropdown]').boundingBox()
  assert.ok(dropdown.x >= 0 && dropdown.x + dropdown.width <= 320 && dropdown.y + dropdown.height <= 640, JSON.stringify(dropdown))
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  await page.keyboard.press('Escape')
  await choose('العربية')
  const systemNotice = 'فُتِح باب الأرشيف.'
  await page.evaluate(text => window.groupedActionsFixture.addSystemNotice(text), systemNotice)
  const systemProse = page.getByText(systemNotice, { exact: true })
  await systemProse.waitFor()
  assert.equal(await systemProse.getAttribute('dir'), 'rtl', 'Localized system prose needs its own direction, separate from its English badge.')
  assert.equal(await systemProse.evaluate(node => getComputedStyle(node).fontStyle), 'normal')
  assert.ok(fontRequests.every(url => new URL(url).origin === new URL(base).origin))
  assert.deepEqual(failedFonts, [])
  assert.deepEqual(errors, [])
  console.log('PASS: six local font families, saved-language switching, teleported settings fonts, actual glyph fonts, Arabic direction, failed save retention, same-origin assets and mobile selector bounds.')
} finally { await browser.close() }
