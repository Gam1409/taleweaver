import process from 'node:process'
import { checkAuthoring } from './authoringChecks.mjs'
import { checkAuthoringDialogs } from './authoringDialogChecks.mjs'
import { checkAuthoringImport } from './authoringImportChecks.mjs'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
try {
  const url = (process.env.FRONTEND_URL || 'http://127.0.0.1:5203') + '/tests/browser/portalPreview.html'
  await checkAuthoring(await browser.newPage(), url)
  await checkAuthoringDialogs(await browser.newPage(), url)
  await checkAuthoringImport(await browser.newPage(), url)
  console.log('Adventure creation payloads, mode switches, all 15 editor sections, saved metadata, map arrows and mobile layouts passed.')
} finally { await browser.close() }
