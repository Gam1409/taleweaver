import process from 'node:process'
import { checkLoginLayout } from './loginLayoutChecks.mjs'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
try {
  await checkLoginLayout(await browser.newPage(), (process.env.FRONTEND_URL || 'http://127.0.0.1:5203') + '/tests/browser/portalPreview.html')
  console.log('Login artwork, attribution, licenses, scrolling, password controls, sign-in and recovery passed with fictional data.')
} finally { await browser.close() }
