import assert from 'node:assert/strict'

async function visibleHit(locator, label) {
  await locator.scrollIntoViewIfNeeded()
  assert.equal(await locator.evaluate(node => {
    const rect = node.getBoundingClientRect()
    const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2)
    return hit === node || node.contains(hit)
  }), true, label)
}

export async function checkScriptEditorLayout(page, url, { offline = true } = {}) {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  if (offline) await page.route(/^https:\/\/(cdnjs\.cloudflare\.com|cdn\.jsdelivr\.net)\//, route => route.abort())
  page.setDefaultTimeout(12000)
  await page.setViewportSize({ width: 720, height: 500 })
  await page.goto(url + '?screen=editor')
  await page.locator('#editor-section').selectOption('scripts')
  await page.getByRole('button', { name: 'New Script', exact: true }).click()
  const modal = page.locator('.authoring-dialog').filter({ has: page.getByRole('heading', { name: 'Create Event Script', exact: true }) })
  await modal.waitFor()
  await visibleHit(modal.getByRole('heading', { name: 'Create Event Script', exact: true }), 'Script dialog header is above the page headers')
  const editor = modal.locator('.script-editor-container')
  const code = 'tw.vars.set("layout_check", True)'
  let engine = null
  if (offline) await editor.locator('textarea').fill(code)
  else {
    await editor.locator('.CodeMirror').waitFor()
    await editor.locator('.CodeMirror').evaluate((node, value) => node.CodeMirror.setValue(value), code)
    engine = await editor.locator('.CodeMirror').evaluateHandle(node => node.CodeMirror)
  }
  for (const [width, height] of [[720, 500], [320, 400]]) {
    await page.setViewportSize({ width, height })
    await editor.getByTitle('Expand Fullscreen', { exact: true }).click()
    const fullscreen = page.locator('.script-editor-container').filter({ has: page.getByTitle('Exit Fullscreen', { exact: true }) })
    const exit = fullscreen.getByTitle('Exit Fullscreen', { exact: true })
    await visibleHit(exit, 'Fullscreen exit is not clipped or covered')
    if (width === 320) {
      await fullscreen.getByTitle('Insert Code Snippet', { exact: true }).focus()
      const snippet = fullscreen.getByRole('button', { name: 'System Notification', exact: true })
      assert.equal(await snippet.evaluate(node => {
        const popup = node.parentElement.getBoundingClientRect()
        const editor = node.closest('.script-editor-container').getBoundingClientRect()
        return popup.left >= editor.left && popup.right <= editor.right && popup.bottom <= editor.bottom
      }), true, 'The snippet popup fits inside the narrow editor')
      await fullscreen.getByTitle('TaleWeaver Scripting Guide & Reference (docs/scripting_engine.md)', { exact: true }).click()
      await fullscreen.getByTitle('Verify Python syntax in-browser using Skulpt AST', { exact: true }).click()
      await fullscreen.locator('.script-editor-docs').waitFor()
      await fullscreen.locator('.script-editor-output').waitFor()
    }
    assert.equal(await fullscreen.evaluate(node => {
      const r = node.getBoundingClientRect()
      return r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight && node.scrollWidth <= node.clientWidth
    }), true, 'Fullscreen remains inside the viewport')
    assert.equal(await fullscreen.locator('.codemirror-wrapper').evaluate(node => {
      const canvas = node.parentElement.getBoundingClientRect()
      const editor = node.closest('.script-editor-container').getBoundingClientRect()
      return canvas.height > 0 && canvas.bottom <= editor.bottom
    }), true, 'The code canvas fits inside the fullscreen editor')
    await exit.click()
    if (offline) assert.equal(await editor.locator('textarea').inputValue(), code)
    else {
      assert.equal(await editor.locator('.CodeMirror').evaluate(node => node.CodeMirror.getValue()), code)
      assert.equal(await editor.locator('.CodeMirror').evaluate((node, previous) => node.CodeMirror === previous, engine), true, 'Moving the editor preserves its engine instance')
    }
  }
  await engine?.dispose()
  await page.setViewportSize({ width: 720, height: 500 })
  await modal.getByRole('button', { name: 'Create Script', exact: true }).click()
  await modal.waitFor({ state: 'hidden' })
  await page.waitForFunction(() => window.portalFixture.writes.some(write => write.body?.scripts?.some(script => script.code.includes('layout_check'))))
  await page.getByTitle('Delete Script', { exact: true }).first().click()
  const confirm = page.locator('.authoring-dialog').filter({ has: page.getByRole('heading', { name: 'Delete Script', exact: true }) })
  await confirm.waitFor()
  await visibleHit(confirm.getByRole('heading', { name: 'Delete Script', exact: true }), 'Delete dialog is above page headers')
  await confirm.getByRole('button', { name: 'Cancel', exact: true }).click()
  assert.equal(await page.getByRole('button', { name: 'Edit', exact: true }).count(), 1)
  assert.deepEqual(await page.evaluate(() => window.portalFixture.unhandled), [])
  assert.deepEqual(errors, [])
}
