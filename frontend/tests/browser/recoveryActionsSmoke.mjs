import assert from 'node:assert/strict'
import process from 'node:process'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1360, height: 1000 } })
const errors = [], requests = []
page.on('pageerror', error => errors.push(error.message))
page.setDefaultTimeout(10000)
let checks = 0, loads = 0
try {
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url())
    requests.push({ path: url.pathname, body: request.postDataJSON() })
    if (url.pathname.endsWith('/chat/replay')) return route.fulfill({
      status: ++checks === 1 ? 503 : 200, json: { available: true, message_id: 'answer' },
    })
    if (url.pathname.endsWith('/items/COAT/repair')) return route.fulfill({
      status: ++loads === 1 ? 503 : 200, json: { before_hash: `current-${loads}`,
        item: { name: 'White coat', description: 'A wool coat.', item_type: 'DEFAULT' } },
    })
    if (url.pathname.endsWith('/repair/preview')) return route.fulfill({
      status: 409, json: { detail: 'The item or its owner changed.' },
    })
    if (url.pathname.endsWith('/chat/narration-versions')) return route.fulfill({ json: { versions: [] } })
    throw new Error(`Unexpected fixture request: ${url.pathname}`)
  })
  await page.goto((process.env.FRONTEND_URL || 'http://127.0.0.1:5205') + '/tests/browser/recoveryActions.html')
  const fixes = page.getByRole('dialog', { name: 'AI Fix Suggestions' })
  await fixes.getByRole('button', { name: 'Generate fresh suggestions' }).click()
  assert.equal(await page.locator('#retries').textContent(), '1')
  await page.keyboard.press('Escape')
  await fixes.waitFor({ state: 'hidden' })
  const regenerate = page.getByRole('button', { name: 'Regenerate turn', exact: true })
  assert.equal(await regenerate.isDisabled(), true)
  await page.getByRole('button', { name: 'Retry turn check' }).click()
  await regenerate.waitFor()
  await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(button => button.textContent.trim() === 'Regenerate turn')?.disabled)
  await page.getByRole('button', { name: 'Toggle evaluation lock' }).click()
  assert.equal(await regenerate.isDisabled(), true)
  await page.getByRole('button', { name: 'Repair Coat', exact: true }).click()
  const repair = page.getByRole('dialog', { name: 'Repair item — Coat', exact: true })
  await repair.getByRole('button', { name: 'Retry loading item' }).click()
  const description = repair.getByRole('textbox', { name: 'Full description' })
  await description.fill('My unsaved detailed coat description.')
  await repair.getByRole('button', { name: 'Generate text & technical draft' }).click()
  await repair.getByRole('alert').filter({ hasText: 'The item or its owner changed.' }).waitFor()
  page.once('dialog', dialog => dialog.dismiss())
  await repair.getByRole('button', { name: 'Reload saved item' }).click()
  assert.equal(await description.inputValue(), 'My unsaved detailed coat description.')
  assert.equal(loads, 2)
  page.once('dialog', dialog => dialog.accept())
  await repair.getByRole('button', { name: 'Reload saved item' }).click()
  await page.waitForFunction(() => document.querySelector('dialog textarea')?.value === 'A wool coat.')
  assert.equal(loads, 3)
  assert.equal(requests.some(request => request.path.endsWith('/apply')), false)
  assert.deepEqual(errors, [])
  console.log('Recovery actions browser checks passed: empty AI Fix, snapshot retry and locks, repair retry and confirmed reload.')
} finally {
  await browser.close()
}
