import assert from 'node:assert/strict'

export async function checkAuthoringImport(page, url) {
  const nativeDialogs = []
  page.on('dialog', async dialog => { nativeDialogs.push(dialog.message()); await dialog.dismiss() })
  for (const width of [1440, 320]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto(url + '?screen=editor')
    await page.locator('.authoring-content').waitFor()
    if (width < 1024) await page.locator('#editor-section').selectOption('protagonist')
    else await page.getByRole('navigation', { name: 'Adventure sections' }).getByRole('button', { name: 'Protagonist', exact: true }).click()
    const trigger = page.getByTitle('Replace the protagonist with one from a .twe file', { exact: true })
    const dialog = page.getByRole('dialog', { name: 'Import protagonist?' })
    await trigger.click()
    await dialog.waitFor()
    assert.equal(await dialog.evaluate(node => getComputedStyle(node).backgroundColor), 'rgb(16, 24, 39)')
    assert.equal(await dialog.evaluate(node => node.scrollWidth > node.clientWidth), false)
    assert.match(await dialog.innerText(), /Inventory and equipment are kept/)
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
    await dialog.waitFor({ state: 'hidden' })
    assert.equal(await trigger.evaluate(node => document.activeElement === node), true)
    await trigger.click()
    await dialog.waitFor()
    await page.keyboard.press('Escape')
    await dialog.waitFor({ state: 'hidden' })
    await trigger.click()
    await dialog.waitFor()
    await page.mouse.click(2, 2)
    await dialog.waitFor({ state: 'hidden' })
    await trigger.click()
    await dialog.waitFor()
    const picker = page.waitForEvent('filechooser')
    await dialog.getByRole('button', { name: 'Choose bundle', exact: true }).click()
    const chooser = await picker
    assert.equal(chooser.isMultiple(), false)
    await chooser.setFiles([])
    await dialog.waitFor({ state: 'hidden' })
    assert.equal(await page.evaluate(() => window.portalFixture.writes.some(write => write.path.includes('/import'))), false)
  }
  assert.deepEqual(nativeDialogs, [])
}
