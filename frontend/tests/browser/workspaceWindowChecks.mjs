import assert from 'node:assert/strict'

export async function checkWorkspaceWindowInventory(page, url) {
  const windows = ['delete-adventure', 'delete-adventures', 'import-examples', 'import-warning', 'delete-session', 'delete-sessions', 'session-note', 'about', 'import-conflict', 'setup', 'clone', 'export', 'generation', 'migrate', 'user', 'catalog', 'prompt', 'memory', 'licenses', 'credentials', 'workflow', 'assignments', 'presets']
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }, { width: 320, height: 568 }, { width: 800, height: 420 }]) {
    await page.setViewportSize(viewport)
    for (const name of windows) {
      await page.goto(`${url}?window=${name}`)
      if (name === 'memory') await page.getByRole('button', { name: 'Memory index', exact: true }).click()
      if (name === 'workflow') await page.getByRole('button', { name: 'Open workflow editor', exact: true }).click()
      if (name === 'assignments') await page.getByRole('button', { name: 'Manage presets & assignments', exact: true }).click()
      const panel = page.locator('.workspace-dialog:visible').last()
      await panel.waitFor()
      await page.waitForTimeout(300)
      const box = await panel.boundingBox()
      const label = `${name} ${viewport.width}×${viewport.height}`
      assert.ok(box.x >= -1 && box.y >= -1 && box.x + box.width <= viewport.width + 1 && box.y + box.height <= viewport.height + 1, `${label} must fit the viewport`)
      assert.equal(await panel.evaluate(node => node.scrollWidth > node.clientWidth), false, `${label} must contain its controls`)
      assert.match(await panel.evaluate(node => getComputedStyle(node).fontFamily), /Alegreya Sans/, label)
      assert.deepEqual(await page.evaluate(() => window.workspaceWindows.unhandled), [], label)
    }
  }
  assert.deepEqual(errors, [])
}
