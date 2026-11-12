import assert from 'node:assert/strict'

export async function checkIntelligenceLayout(page, url) {
  page.setDefaultTimeout(15000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto(url + '?section=admin')
  await page.locator('aside nav button').nth(1).click()
  await page.getByRole('heading', { name: 'Intelligence Routing' }).waitFor()
  assert.equal(await page.getByText('Technical output compatibility', { exact: true }).count(), 0)
  const general = role => page.locator(`details[data-general-role="${role}"]`)
  assert.equal(await page.locator('details[data-general-role]').count(), 5)
  for (const role of ['small', 'complex', 'generator', 'play_agent', 'compression']) {
    assert.equal(await general(role).getAttribute('open'), null)
    assert.equal(await general(role).getByLabel('Allow parallel requests', { exact: true }).isVisible(), false)
  }
  await general('small').locator('summary').click()
  await general('small').getByLabel('Allow parallel requests', { exact: true }).check()
  await page.locator('#parallel-small-limit').selectOption('3')
  await general('small').locator('summary').click()
  await page.getByRole('button', { name: 'Worldbuilder (Adventure Gen)', exact: true }).click()
  await page.getByRole('button', { name: 'All Passes (5)', exact: true }).click()
  await general('small').locator('summary').click()
  assert.equal(await general('small').getByLabel('Allow parallel requests', { exact: true }).isChecked(), true)
  assert.equal(await page.locator('#parallel-small-limit').inputValue(), '3')
  await page.getByRole('button', { name: /Save Routing/ }).click()
  await page.waitForFunction(() => window.portalFixture.requests.includes('POST /settings/llm'))
  await page.getByRole('button', { name: 'Return to Portal', exact: true }).click()
  await page.getByRole('navigation', { name: 'Workspace', exact: true }).getByRole('button', { name: 'Administration', exact: true }).click()
  await page.locator('aside nav button').nth(1).click()
  await general('small').locator('summary').click()
  assert.equal(await general('small').getByLabel('Allow parallel requests', { exact: true }).isChecked(), true)
  assert.equal(await page.locator('#parallel-small-limit').inputValue(), '3')
  for (const width of [976, 390, 320]) {
    await page.setViewportSize({ width, height: 844 })
    const navigation = page.getByRole('navigation', { name: 'Intelligence sections', exact: true })
    assert.equal(await navigation.evaluate(el => el.scrollWidth <= el.clientWidth), true)
    await navigation.getByRole('button', { name: 'Local Endpoints & Memory', exact: true }).click()
    await page.screenshot({ path: `/tmp/taleweaver-intelligence-${width}.png` })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  }
  assert.deepEqual(errors, [])
  assert.deepEqual(await page.evaluate(() => window.portalFixture.unhandled), [])
}
