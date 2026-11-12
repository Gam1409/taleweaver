import process from 'node:process'
import { checkPortalWorkspace } from './portalWorkspaceChecks.mjs'

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
try {
  const page = await browser.newPage()
  await checkPortalWorkspace(page, (process.env.FRONTEND_URL || 'http://127.0.0.1:5203') + '/tests/browser/portalPreview.html')
  console.log('Portal navigation, filters, confirmations, profile, administration and mobile checks passed.')
} finally {
  await browser.close()
}
