import assert from 'node:assert/strict'

export async function checkWorkspaceDialogs(page, url) {
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 844 })
    const openAdmin = async section => {
      await page.goto(url + '?section=admin')
      if (width < 1024) await page.locator('#admin-section').selectOption(section)
      else await page.locator('aside nav button').nth({ keys: 0, styles: 5, users: 9 }[section]).click()
    }
    const checkPanel = async () => {
      const panel = page.locator('.workspace-dialog:visible').last()
      await panel.waitFor()
      await page.waitForTimeout(250)
      const box = await panel.boundingBox()
      assert.ok(box.x >= 0 && box.x + box.width <= width + 1 && box.y >= 0 && box.y + box.height <= 845)
      assert.equal(await panel.evaluate(node => node.scrollWidth > node.clientWidth), false, 'Dialog controls must fit the panel')
      assert.match(await panel.evaluate(node => getComputedStyle(node).fontFamily), /Alegreya Sans/)
    }
    await openAdmin('keys')
    await page.getByRole('button', { name: 'Update Key', exact: true }).first().click()
    await checkPanel()
    await openAdmin('styles')
    await page.getByRole('button', { name: 'Add Style', exact: true }).click()
    await checkPanel()
    await openAdmin('styles')
    await page.getByTitle('Options', { exact: true }).first().click()
    await page.getByRole('button', { name: 'Custom Prompt', exact: true }).click()
    await checkPanel()
    await openAdmin('users')
    await page.getByRole('button', { name: 'Add User', exact: true }).click()
    await checkPanel()
    await page.goto(url)
    await page.getByRole('button', { name: 'Manage', exact: false }).click()
    await page.getByRole('menuitem', { name: /Delete all adventures/ }).click()
    await checkPanel()
    await page.goto(url)
    await page.getByRole('button', { name: 'Import samples', exact: true }).click()
    await checkPanel()
    await page.goto(url)
    await page.getByRole('button', { name: 'Grid view', exact: true }).click()
    await page.evaluate(() => {
      const respond = window.portalFixture.respond
      window.portalFixture.respond = (path, ...args) => path.endsWith('/sessions/start') ? new Promise(() => {}) : respond(path, ...args)
    })
    await page.getByRole('button', { name: 'Start', exact: true }).first().click()
    await page.getByRole('heading', { name: 'Session Is Starting', exact: true }).waitFor()
    await checkPanel()
    assert.deepEqual(await page.evaluate(() => window.portalFixture.unhandled), [])
  }
}
