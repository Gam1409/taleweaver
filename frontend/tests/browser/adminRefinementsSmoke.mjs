import process from 'node:process'
import { checkIntelligenceLayout } from './intelligenceLayoutChecks.mjs'
import { checkWorkspacePolish } from './workspacePolishChecks.mjs'
import { checkFooterLicenses } from './footerLicensesChecks.mjs'

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
try {
  const page = await browser.newPage()
  const url = (process.env.FRONTEND_URL || 'http://127.0.0.1:5203') + '/tests/browser/portalPreview.html'
  await checkIntelligenceLayout(page, url)
  await checkFooterLicenses(page, url)
  await checkWorkspacePolish(page, url)
  console.log('Intelligence layout, saved concurrency settings, footer attribution and full license texts passed.')
} finally {
  await browser.close()
}
