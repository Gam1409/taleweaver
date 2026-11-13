import assert from 'node:assert/strict'
import process from 'node:process'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
const base = process.env.FRONTEND_URL || 'http://127.0.0.1:5215'
const failures = []
async function check(name, action) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' })
  page.setDefaultTimeout(10000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  try {
    await page.goto(base + '/tests/browser/worldInfo.html?records=120')
    await action(page)
    assert.deepEqual(errors, [])
    console.log(`PASS ${name}`)
  } catch (error) {
    failures.push(`${name}: ${error.message}`)
    console.error(`FAIL ${name}: ${error.message}`)
  } finally { await page.close() }
}
const dialog = page => page.locator('dialog[open]')
const button = (page, name) => dialog(page).getByRole('button', { name, exact: true })
async function open(page) {
  await page.getByRole('button', { name: 'Session', exact: true }).click()
  await page.getByRole('menuitem', { name: /World Info/ }).click()
  await dialog(page).getByRole('tab', { name: 'Review', exact: true }).click()
  await dialog(page).locator('[data-world-info-entry="entry-beacon"]').waitFor()
}
async function edit(page) {
  await dialog(page).locator('[data-world-info-entry="entry-beacon"]').click()
  await button(page, 'Edit entry').click()
}
async function tagInput(page, label) {
  return dialog(page).getByRole('group', { name: label, exact: true }).getByRole('textbox').first()
}
async function addTags(page, label, tags) {
  const fields = dialog(page).getByRole('group', { name: label, exact: true })
  for (const tag of tags) {
    await fields.getByRole('button', { name: 'Add tag', exact: true }).click()
    await fields.getByRole('textbox').last().fill(tag)
  }
}
try {
  await check('relationship Enter searches without saving', async page => {
    await open(page); await edit(page)
    await dialog(page).getByLabel('Entry title', { exact: true }).fill('Pending relationship search')
    await dialog(page).locator('summary').filter({ hasText: 'Relationships between entries' }).click()
    await dialog(page).getByLabel('Find a session entry', { exact: true }).fill('old coastal')
    await dialog(page).getByLabel('Find a session entry', { exact: true }).press('Enter')
    await page.waitForFunction(() => window.worldInfoFixture.requests.some(value => value.path.includes('/entries?') && new URL(value.path, location.origin).searchParams.get('query') === 'old coastal'))
    assert.equal(await page.evaluate(() => window.worldInfoFixture.writes.length), 0)
    assert.equal(await dialog(page).getByLabel('Entry title', { exact: true }).inputValue(), 'Pending relationship search')
    await button(page, 'Save entry').click(); await button(page, 'Edit entry').waitFor()
    assert.equal(await page.evaluate(() => window.worldInfoFixture.writes.length), 1)
  })
  await check('tag-only typing is dirty before blur and saves after keeping the draft', async page => {
    await open(page); await edit(page)
    await (await tagInput(page, 'Tags / hashtags')).fill('#harbour history, exact')
    await page.keyboard.press('Escape')
    assert.equal(await dialog(page).getByRole('heading', { name: 'Discard unsaved entry changes?' }).count(), 1)
    await button(page, 'Keep current state').click()
    assert.equal(await (await tagInput(page, 'Tags / hashtags')).inputValue(), '#harbour history, exact')
    await button(page, 'Save entry').click(); await button(page, 'Edit entry').waitFor()
    const saved = await page.evaluate(() => window.worldInfoFixture.writes.at(-1).body)
    assert.deepEqual(saved.tags, ['#harbour history, exact', 'lighthouse'])
  })
  await check('editing and bulk removal preserve exact hashtag, space and comma identities', async page => {
    const originals = ['#harbour', 'harbour history', 'trade,craft', 'harbour', 'line\r\nbreak\tlabel']
    await page.evaluate(tags => window.worldInfoFixture.setFirstEntryTags('world-info-demo', tags), originals)
    await open(page); await edit(page)
    await addTags(page, 'Tags / hashtags', ['new, exact #label'])
    await button(page, 'Save entry').click(); await button(page, 'Edit entry').waitFor()
    const saved = await page.evaluate(() => window.worldInfoFixture.writes.at(-1).body)
    assert.deepEqual(saved.tags, [...originals, 'new, exact #label'])
    assert.equal(await dialog(page).locator('.world-info-read-tag').filter({ hasText: '##harbour' }).count(), 0)
    await button(page, 'Back to catalog').click()
    await dialog(page).locator('.world-info-bulk').evaluate(node => { node.open = true })
    await dialog(page).getByLabel('Bulk action', { exact: true }).selectOption('remove_tags')
    await addTags(page, 'Tags for matching entries', originals.slice(0, 3))
    await dialog(page).getByRole('group', { name: 'Tags for matching entries', exact: true }).getByLabel('Add a saved tag', { exact: true }).selectOption(originals[4])
    await button(page, 'Preview matching entries').click()
    await dialog(page).getByRole('region', { name: 'Bulk action preview' }).waitFor()
    const tags = dialog(page).getByRole('group', { name: 'Tags for matching entries', exact: true })
    await tags.getByRole('button', { name: 'Add tag', exact: true }).click()
    assert.equal(await dialog(page).getByRole('region', { name: 'Bulk action preview' }).count(), 0)
    await tags.getByRole('textbox').last().fill('temporary')
    await button(page, 'Preview matching entries').click()
    await dialog(page).getByRole('region', { name: 'Bulk action preview' }).waitFor()
    await tags.getByRole('button', { name: 'Remove tag 5', exact: true }).click()
    assert.equal(await dialog(page).getByRole('region', { name: 'Bulk action preview' }).count(), 0)
    await button(page, 'Preview matching entries').click()
    await dialog(page).getByRole('region', { name: 'Bulk action preview' }).waitFor()
    await button(page, 'Confirm matching changes').click(); await button(page, 'Confirm').click()
    await dialog(page).getByText(/Confirmed changes saved/).waitFor()
    const applied = await page.evaluate(() => window.worldInfoFixture.writes.filter(value => value.path === '/entries/bulk/apply').at(-1).body)
    assert.deepEqual(applied.tags, [...originals.slice(0, 3), originals[4]])
    await edit(page)
    assert.deepEqual(await dialog(page).getByRole('group', { name: 'Tags / hashtags', exact: true }).getByRole('textbox').evaluateAll(nodes => nodes.map(node => node.value)), ['harbour', 'new, exact #label'])
    await dialog(page).getByLabel('Summary', { exact: true }).fill('An unrelated field edit keeps exact labels.')
    await button(page, 'Save entry').click(); await button(page, 'Edit entry').waitFor()
    assert.deepEqual(await page.evaluate(() => window.worldInfoFixture.writes.filter(value => value.path === '/entries/entry-beacon').at(-1).body.tags), ['harbour', 'new, exact #label'])
  })
  for (const action of ['publish', 'bulk']) await check(`pending ${action} keeps detail navigation closed`, async page => {
    await page.evaluate(action => {
      const original = window.fetch, suffix = action === 'publish' ? '/world-info/publish' : '/world-info/entries/bulk/apply'
      window.fetch = async (input, options) => {
        const response = await original(input, options)
        if (String(input).endsWith(suffix)) return new Promise(resolve => { window.finishWorldInfoMutation = () => resolve(response) })
        return response
      }
    }, action)
    await open(page)
    if (action === 'publish') {
      await dialog(page).getByLabel('Select The harbour beacon', { exact: true }).check()
      await button(page, 'Publish selected (1)').click()
    } else {
      await dialog(page).locator('.world-info-bulk').evaluate(node => { node.open = true })
      await dialog(page).getByLabel('Group name', { exact: true }).fill('Confirmed group')
      await button(page, 'Preview matching entries').click()
      await dialog(page).getByRole('region', { name: 'Bulk action preview' }).waitFor()
      await button(page, 'Confirm matching changes').click()
    }
    await button(page, 'Confirm').click()
    await page.waitForFunction(() => typeof window.finishWorldInfoMutation === 'function')
    const row = dialog(page).locator('[data-world-info-entry="entry-route"]')
    assert.equal(await row.isDisabled(), true)
    await row.evaluate(node => node.click())
    await row.locator('xpath=ancestor::tr').locator('td').last().click()
    assert.equal(await page.evaluate(() => window.worldInfoFixture.requests.filter(value => value.path.endsWith('/entries/entry-route')).length), 0)
    assert.equal(await dialog(page).getByRole('tab', { name: 'Review', exact: true }).count(), 1)
    await page.evaluate(() => window.finishWorldInfoMutation())
    await dialog(page).getByText(action === 'publish' ? /Selected entries are accepted/ : /Confirmed changes saved/).waitFor()
    await row.click(); await button(page, 'Edit entry').waitFor()
  })
  assert.deepEqual(failures, [])
} finally { await browser.close() }
