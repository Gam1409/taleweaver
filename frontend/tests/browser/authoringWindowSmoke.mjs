import assert from 'node:assert/strict'
import process from 'node:process'
import { writeFile } from 'node:fs/promises'
import { authoringWindowCases, checkAuthoringWindows } from './authoringWindowChecks.mjs'
import { authoringWindowInventory } from './authoringWindowInventory.mjs'
const key = entry => `${entry.file}#${entry.window || 0}`
assert.deepEqual(authoringWindowCases.map(key).sort(), authoringWindowInventory().map(key).sort(), 'Every discovered authoring dialog needs an explicit browser case')
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
try {
  const rows = await checkAuthoringWindows(await browser.newPage({ reducedMotion: 'reduce' }), process.env.FRONTEND_URL || 'http://127.0.0.1:5203', { onRow: row => console.log(`${row.status.toUpperCase()} ${row.id} ${row.width}x${row.height}${row.error ? ': ' + row.error.slice(0, 200) : ''}`) })
  await writeFile('/tmp/authoring-window-coverage.json', JSON.stringify(rows, null, 2))
  assert.deepEqual(rows.filter(row => row.status !== 'pass').map(row => ({ id: row.id, width: row.width, error: row.error })), [])
  console.log(`PASS: ${rows.length} authoring window checks; coverage saved to /tmp/authoring-window-coverage.json`)
} finally { await browser.close() }
