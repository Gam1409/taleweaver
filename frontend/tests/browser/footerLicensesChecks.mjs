import assert from 'node:assert/strict'

export async function checkFooterLicenses(page, url) {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto(url)
  const trigger = page.getByRole('button', { name: 'Licenses', exact: true })
  await trigger.waitFor()
  assert.match(await page.locator('.workspace-footer').textContent(), /© 2026 Anton Kuprin \(fork of TaleWeaver by Jean Schmitz\)/)
  await trigger.click()
  const modal = page.getByRole('dialog', { name: 'Licenses', exact: true })
  const body = modal.getByRole('region', { name: 'License text', exact: true })
  await body.getByText(/Copyright \(c\) 2026 Jean Schmitz/).waitFor()
  const select = modal.getByLabel('License document', { exact: true })
  const options = await select.locator('option').evaluateAll(nodes => nodes.map(node => node.value))
  assert.equal(options.length, 21)
  for (const value of options) {
    await select.selectOption(value)
    await page.waitForFunction(() => document.querySelector('[aria-label="License text"]').getAttribute('aria-busy') === 'false')
    assert.ok((await body.innerText()).length > 200, value)
    assert.equal(await modal.getByRole('alert').count(), 0, value)
  }
  await select.selectOption('application')
  await body.getByText(/Copyright \(c\) 2026 Jean Schmitz/).waitFor()
  const downloadEvent = page.waitForEvent('download')
  await modal.getByRole('link', { name: 'Download text', exact: true }).click()
  const download = await downloadEvent
  assert.equal(download.suggestedFilename(), 'taleweaver-MIT.txt')
  await download.delete()
  await page.keyboard.press('Escape')
  await modal.waitFor({ state: 'hidden' })
  assert.equal(await trigger.evaluate(node => node === document.activeElement), true)
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 })
    await trigger.click()
    await modal.getByLabel('License document').selectOption('samples')
    await body.getByText(/Creative Commons Attribution-NonCommercial 4.0 International/).waitFor()
    const bounds = await modal.boundingBox()
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width)
    assert.equal(await modal.evaluate(node => node.scrollWidth <= node.clientWidth), true)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
    await page.screenshot({ path: `/tmp/taleweaver-licenses-${width}.png` })
    await modal.getByRole('button', { name: 'Close licenses', exact: true }).click()
  }
}
