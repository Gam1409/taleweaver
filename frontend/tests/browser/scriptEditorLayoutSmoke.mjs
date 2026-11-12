import process from 'node:process'
import { checkScriptEditorLayout } from './scriptEditorLayoutChecks.mjs'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
try {
  await checkScriptEditorLayout(await browser.newPage(), (process.env.FRONTEND_URL || 'http://127.0.0.1:5203') + '/tests/browser/portalPreview.html', { offline: process.env.SCRIPT_EDITOR_ONLINE !== '1' })
  console.log('Script dialog stacking, bounded fullscreen, retained code, save and cancel passed.')
} finally { await browser.close() }
