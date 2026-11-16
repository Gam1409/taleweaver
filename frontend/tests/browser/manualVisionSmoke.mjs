import assert from 'node:assert/strict'
import process from 'node:process'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1360, height: 1100 } })
const errors = [], requests = []
page.on('pageerror', error => errors.push(error.message))
page.setDefaultTimeout(10000)
let releaseOld
const heldResponse = new Promise(resolve => { releaseOld = resolve })
try {
  await page.route('**/api/adventures/adventure/visuals/suggest-prompt', async route => {
    requests.push(route.request().postDataJSON())
    const call = requests.length
    if (call === 1) await heldResponse
    await route.fulfill({ status: call === 2 ? 503 : 200,
      json: call === 2 ? { detail: 'The prompt provider is unavailable. Please retry.' }
        : { suggested_prompt: call === 1 ? 'Old Alice prompt.' : 'New Beatrice prompt.' } })
  })
  await page.goto((process.env.FRONTEND_URL || 'http://127.0.0.1:5205') + '/tests/browser/manualVision.html')
  const suggest = page.getByRole('button', { name: 'Suggest Prompt', exact: true })
  const start = page.waitForRequest(request => request.url().endsWith('/suggest-prompt'))
  await suggest.click()
  await start
  assert.equal(await page.getByRole('button', { name: 'Generate Vision' }).isDisabled(), true)
  const canceled = page.waitForEvent('requestfailed', { predicate: request => request.url().endsWith('/suggest-prompt') })
  await page.getByRole('button', { name: 'Abort', exact: true }).click()
  await canceled
  await page.getByRole('button', { name: 'Edit Beatrice' }).click()
  const prompt = page.locator('textarea')
  assert.equal(await prompt.inputValue(), 'My Beatrice prompt.')
  releaseOld()
  await suggest.click()
  await page.getByRole('alert').filter({ hasText: 'The prompt provider is unavailable.' }).waitFor()
  assert.equal(await prompt.inputValue(), 'My Beatrice prompt.')
  assert.equal(await suggest.isEnabled(), true)
  await suggest.click()
  await page.waitForFunction(() => document.querySelector('textarea')?.value === 'New Beatrice prompt.')
  assert.equal(await page.getByRole('alert').count(), 0)
  assert.deepEqual(requests.map(request => request.target_id), ['ALICE', 'BEATRICE', 'BEATRICE'])
  assert.doesNotMatch(await page.locator('#notices').textContent(), /Alice|abort/i)
  assert.deepEqual(errors, [])
  console.log('Manual vision browser checks passed: prompt abort reaches HTTP, target isolation, inline error, and retry.')
} finally {
  releaseOld()
  await browser.close()
}
