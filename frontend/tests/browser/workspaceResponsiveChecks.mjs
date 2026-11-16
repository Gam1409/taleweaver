import assert from 'node:assert/strict'

export async function checkWorkspaceResponsive(page, url) {
  for (const width of [320, 390, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: 844 })
    await page.goto(url + '?section=admin')
    const selector = page.locator('#admin-section')
    await selector.waitFor({ state: width < 1024 ? 'visible' : 'attached' })
    const sections = await selector.locator('option').evaluateAll(nodes => nodes.map(node => node.value))
    for (const [index, section] of sections.entries()) {
      if (width < 1024) await selector.selectOption(section)
      else await page.locator('aside nav button').nth(index).click()
      const content = page.locator('.workspace-admin > main')
      assert.equal(await content.evaluate(node => node.scrollWidth > node.clientWidth), false, `${section} at ${width}px must fit its scroll region`)
      if (section === 'users') {
        const table = page.locator('.workspace-admin table')
        assert.equal(await table.evaluate(node => node.scrollWidth <= node.parentElement.clientWidth || ['auto', 'scroll'].includes(getComputedStyle(node.parentElement).overflowX)), true, 'User actions must remain reachable through a table scroll region')
      }
    }
    await page.goto(url)
    await page.getByRole('heading', { name: 'Library', exact: true }).waitFor()
    for (const view of ['Grid view', 'Table view']) {
      await page.getByRole('button', { name: view, exact: true }).click()
      assert.equal(await page.locator('.workspace-content').evaluate(node => node.scrollWidth > node.clientWidth), false, `${view} at ${width}px must not clip filters`)
    }
    await page.getByLabel('Filter by narrative tone', { exact: true }).evaluate(node => { node.options[0].text = 'A long custom narrative tone '.repeat(8) })
    assert.equal(await page.locator('.workspace-content').evaluate(node => node.scrollWidth > node.clientWidth), false, `Custom catalog labels at ${width}px must stay within the filters`)
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Open menu', exact: true }).click()
  await page.getByRole('dialog', { name: 'Workspace menu', exact: true }).waitFor()
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.waitForFunction(() => getComputedStyle(document.querySelector('.workspace-sidebar')).position === 'relative')
  assert.equal(await page.locator('.workspace-sidebar').getAttribute('aria-modal'), null, 'A resized mobile drawer must return to desktop navigation')
}
