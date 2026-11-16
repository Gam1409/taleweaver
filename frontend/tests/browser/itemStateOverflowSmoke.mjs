import process from 'node:process'
import { checkItemStateOverflow } from './itemStateOverflowChecks.mjs'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] })
try {
  await checkItemStateOverflow(await browser.newPage(), (process.env.FRONTEND_URL || 'http://127.0.0.1:5211') + '/tests/browser/itemStateOverflow.html')
  console.log('Bounded item details, scrolling, hover lifetime, keyboard and escaping checks passed.')
} finally { await browser.close() }
