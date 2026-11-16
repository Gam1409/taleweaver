import assert from 'node:assert/strict'

async function menuIsUsable(page, label) {
  const choice = page.locator('button:visible').filter({ hasText: new RegExp(`^${label}$`) })
  await choice.waitFor()
  await page.waitForTimeout(250)
  assert.equal(await choice.evaluate(node => {
    const box = node.getBoundingClientRect()
    const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2)
    return box.y >= 0 && box.bottom <= innerHeight && !!hit && node.contains(hit)
  }), true, `${label} must remain clickable outside the table clipping area`)
}

export async function checkWorkspacePolish(page, url) {
  page.setDefaultTimeout(15000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 })
    await page.goto(url + '?section=sessions')
    await page.getByRole('button', { name: 'Table view', exact: true }).click()
    assert.equal(await page.locator('.workspace-content').evaluate(node => getComputedStyle(node).scrollbarWidth), 'thin')
    const table = page.locator('table')
    await table.locator('tbody tr').last().locator('button').last().click()
    await menuIsUsable(page, 'Delete Session')
    const scroller = table.locator('..')
    assert.equal(await scroller.evaluate(node => node.scrollHeight <= node.clientHeight), true)
    await page.keyboard.press('Escape')
    await table.locator('tbody tr').last().locator('button').last().click()
    await page.locator('button:visible').filter({ hasText: /^Delete Session$/ }).click()
    await page.getByRole('heading', { name: 'Delete session', exact: true }).waitFor()
    await page.getByRole('button', { name: 'Cancel', exact: true }).click()
    const footer = page.locator('.workspace-footer')
    assert.ok(await footer.evaluate(node => parseFloat(getComputedStyle(node).marginTop)) >= 32)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    await page.screenshot({ path: `/tmp/taleweaver-sessions-polish-${width}.png` })
    if (width < 1024) await page.getByRole('button', { name: 'Open menu', exact: true }).click()
    await page.getByRole('button', { name: 'About Archive', exact: true }).click()
    const about = page.getByRole('dialog', { name: 'About TaleWeaver', exact: true })
    await about.waitFor()
    const body = about.getByRole('region', { name: 'About content', exact: true })
    assert.equal(await body.evaluate(node => getComputedStyle(node).scrollbarColor.includes('71, 85, 105')), true)
    await body.evaluate(node => { node.scrollTop = node.scrollHeight })
    await about.getByText(/Every choice is a thread/).waitFor()
    const close = about.getByRole('button', { name: 'Close Archive', exact: true })
    assert.equal(await close.evaluate(node => node.closest('[aria-label="About content"]') === null), true)
    const box = await about.boundingBox()
    assert.ok(box.x >= 0 && box.y >= 0 && box.x + box.width <= width && box.y + box.height <= (width === 1440 ? 1000 : 844))
    await page.screenshot({ path: `/tmp/taleweaver-about-polish-${width}.png` })
    await page.keyboard.press('Escape')
    await about.waitFor({ state: 'hidden' })
  }
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto(url)
  await page.getByRole('button', { name: 'Table view', exact: true }).click()
  await page.locator('table tbody tr').last().locator('button').last().click()
  await menuIsUsable(page, 'Delete Adventure')
  await page.getByRole('menuitem', { name: 'Memory index', exact: true }).click()
  await page.getByRole('dialog', { name: 'Memory index', exact: true }).waitFor()
  await page.getByRole('dialog', { name: 'Memory index', exact: true }).getByRole('button', { name: 'Close', exact: true }).click()
  for (const select of await page.locator('select').all()) {
    assert.equal(await select.evaluate(node => getComputedStyle(node).appearance), 'none')
    assert.ok(await select.evaluate(node => parseFloat(getComputedStyle(node).paddingRight)) >= 32)
    assert.notEqual(await select.evaluate(node => getComputedStyle(node).backgroundImage), 'none')
  }
  assert.deepEqual(errors, [])
  assert.deepEqual(await page.evaluate(() => window.portalFixture.unhandled), [])
}
