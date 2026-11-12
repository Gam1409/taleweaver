import assert from 'node:assert/strict'

export async function checkWorkspaceConfirmations(page, url) {
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto(url + '?section=admin')
  await page.locator('aside nav button').nth(6).click()
  const removeTone = async () => {
    await page.getByTitle('Options', { exact: true }).first().click()
    await page.getByRole('button', { name: 'Delete', exact: true }).click()
    return page.getByRole('dialog', { name: 'Delete narrative tone', exact: true })
  }
  let dialog = await removeTone()
  await dialog.waitFor()
  assert.equal(await dialog.getByRole('button', { name: 'Cancel', exact: true }).evaluate(node => node === document.activeElement), true)
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  assert.deepEqual(await page.evaluate(() => window.portalFixture.writes), [], 'Cancel must not save either catalog')
  dialog = await removeTone()
  await dialog.getByRole('button', { name: 'Delete', exact: true }).click()
  await page.waitForFunction(() => window.portalFixture.writes.some(write => write.path === '/settings/tones'))
  const saves = await page.evaluate(() => window.portalFixture.writes)
  assert.equal(saves.filter(write => write.path === '/settings/image-styles').length, 0, 'Tone deletion must preserve image styles')
  assert.deepEqual(saves.find(write => write.path === '/settings/tones').body.items.map(item => item.id), ['wonder', 'gentle'])

  await page.locator('aside nav button').first().click()
  await page.getByTitle('Delete stored key', { exact: true }).first().click()
  dialog = page.getByRole('dialog', { name: 'Remove provider key', exact: true })
  await dialog.waitFor()
  await page.keyboard.press('Escape')
  await dialog.waitFor({ state: 'hidden' })
  assert.equal(await page.evaluate(() => window.portalFixture.writes.some(write => write.path.startsWith('/settings/keys/'))), false)
  await page.getByTitle('Delete stored key', { exact: true }).first().click()
  await dialog.getByRole('button', { name: 'Remove key', exact: true }).click()
  await page.waitForFunction(() => window.portalFixture.writes.some(write => write.method === 'DELETE' && write.path === '/settings/keys/openai'))
  assert.equal(await page.locator('.confirmation-dialog:visible').count(), 0, 'Key removal must require a single confirmation')

  await page.locator('aside nav button').last().click()
  await page.getByTitle('Delete', { exact: true }).first().click()
  dialog = page.getByRole('dialog', { name: 'Delete user', exact: true })
  await dialog.waitFor()
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  assert.equal(await page.evaluate(() => window.portalFixture.writes.some(write => write.method === 'DELETE' && write.path.startsWith('/users/'))), false)
  assert.deepEqual(await page.evaluate(() => window.portalFixture.unhandled), [])
}
